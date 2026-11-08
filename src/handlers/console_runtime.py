"""Runtime de la consola local: un grafo por comercio y sesiones aisladas.

La consola no pasa por Meta ni por SQS: construye un `InboundMessage` simulado y llama
al mismo grafo del supervisor que usa el REPL. Cada comercio tiene sus propios stores
en memoria (citas, pedidos, drafts, contexto y checkpointer), de modo que dos comercios
nunca comparten estado aunque el proceso sea el mismo.

La Fase A es deliberadamente local: no hay DynamoDB, ni Cognito, ni Prompt Management.
El perfil y los overrides de prompt salen de `TenantConfigService`; la Fase B cambiará
solo el repositorio que hay detrás de ese servicio.
"""

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import boto3
from botocore.exceptions import BotoCoreError, NoRegionError
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from adapters.bedrock import BedrockLLM
from adapters.checkpointer import PortCheckpointSaver, thread_id_de
from adapters.in_memory import (
    InMemoryDraftStore,
    InMemoryEmbeddings,
    InMemoryMemoryStore,
    InMemoryVectorStore,
)
from handlers.console_fake_llm import FakeLLM
from shared.contracts import InboundMessage
from shared.contracts.pending import PendingDraft
from shared.errors import AppError, ValidationError
from shared.logging import get_logger
from shared.ports import ClockPort, LLMMessage, LLMPort, VectorRecord
from slices.appointments.application import drafts as drafts_citas
from slices.appointments.application.graph import build_appointment_graph
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.domain.entities import Appointment
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore
from slices.knowledge_rag.application.graph import build_faq_graph
from slices.orders.application import drafts as drafts_pedidos
from slices.orders.application.graph import build_order_graph
from slices.orders.application.schemas import KitchenHoursDay
from slices.orders.domain.entities import Order, Product
from slices.orders.infrastructure.in_memory import (
    InMemoryCatalog,
    InMemoryLegacyOrders,
    InMemoryOrderRepository,
)
from slices.supervisor.application.graph import build_supervisor_graph
from slices.tenant_prompts.application.service import TenantConfigService
from slices.tenant_prompts.domain.entities import TenantProfile

logger = get_logger(__name__)

LlmMode = Literal["auto", "fake", "bedrock"]

_TENANT_DEMO = "Sede_Elite_01"
_CLIENTE_DEMO = "57300111111"
_HORARIO = tuple(
    OpeningHoursDay(weekday=dia, open_time="09:00", close_time="18:00") for dia in range(5)
)
_COCINA = tuple(
    KitchenHoursDay(weekday=dia, open_time="00:00", close_time="23:59") for dia in range(7)
)


class _RelojLocal:
    """`ClockPort` con la hora local del proceso (naive, como los horarios demo)."""

    def now(self) -> datetime:
        """Devuelve la hora actual del sistema.

        Returns:
            `datetime.now()` naive; el horario demo también es naive.
        """
        return datetime.now()


def _productos_demo(tenant_id: str) -> tuple[Product, ...]:
    """Catálogo sintético del comercio para la consola.

    Args:
        tenant_id: Comercio dueño de los productos.

    Returns:
        Dos productos de ejemplo; los precios reales los aporta el POS/legacy.
    """
    return (
        Product(
            tenant_id=tenant_id,
            sku="A-100",
            name="Alitas BBQ",
            price=18_000,
            category="entradas",
        ),
        Product(
            tenant_id=tenant_id,
            sku="P-100",
            name="Coca-Cola",
            price=5_000,
            category="bebidas",
        ),
    )


def _conocimiento_demo(tenant_id: str, display_name: str) -> tuple[VectorRecord, ...]:
    """Conocimiento sintético para que el grafo FAQ tenga evidencia que citar.

    Args:
        tenant_id: Comercio dueño de los chunks.
        display_name: Nombre comercial usado en los textos.

    Returns:
        Registros vectoriales de ejemplo (sin datos reales de clientes).
    """
    textos = (
        f"Horario de atencion de {display_name}: lunes a viernes 9:00 a 18:00.",
        f"Direccion de {display_name}: Calle 1 #2-3, Sahagun.",
        "Pedidos a domicilio: minimo de compra 20.000 pesos.",
        "Citas: lunes a viernes en horario de atencion.",
    )
    embeddings = InMemoryEmbeddings()
    vectores = embeddings.embed(texts=textos)
    return tuple(
        VectorRecord(
            id=f"demo-{indice}",
            tenant_id=tenant_id,
            text=texto,
            vector=list(vector),
            metadata={"source_type": "faq", "title": display_name},
        )
        for indice, (texto, vector) in enumerate(zip(textos, vectores, strict=True))
    )


class _Confirmer:
    """`ConfirmerPort` de la consola: despacha drafts al especialista dueño.

    Comparte el mismo `InMemoryDraftStore` que los grafos, así que el router del
    supervisor ve exactamente los drafts que crean las tools (ADR 0011).
    """

    def __init__(
        self,
        *,
        drafts: InMemoryDraftStore,
        legacy: InMemoryLegacyOrders,
        repo_citas: InMemoryAppointmentRepository,
        clock: ClockPort,
    ) -> None:
        """Guarda las dependencias comunes de cada despacho.

        Args:
            drafts: Store compartido entre especialistas y router.
            legacy: Backend de pedidos en memoria.
            repo_citas: Repositorio de citas en memoria.
            clock: Reloj para la ventana de deshacer y los drafts.
        """
        self._drafts = drafts
        self._legacy = legacy
        self._repo_citas = repo_citas
        self._clock = clock

    def affirm(self, *, tenant_id: str, draft_id: str, payload_hash: str) -> None:
        """Confirma y ejecuta un draft `AWAITING_CONFIRMATION`.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft a confirmar.
            payload_hash: Hash del contenido exacto confirmado.
        """
        draft = self._draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft.kind == "order":
            drafts_pedidos.confirm_draft(
                tenant_id=tenant_id,
                draft_id=draft_id,
                payload_hash=payload_hash,
                legacy=self._legacy,
                drafts=self._drafts,
                clock=self._clock,
            )
        else:
            drafts_citas.confirm_draft(
                tenant_id=tenant_id,
                draft_id=draft_id,
                payload_hash=payload_hash,
                repo=self._repo_citas,
                drafts=self._drafts,
                clock=self._clock,
            )

    def deny(self, *, tenant_id: str, draft_id: str) -> None:
        """Cancela un draft activo sin ejecutarlo.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft a cancelar.
        """
        draft = self._draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft.kind == "order":
            drafts_pedidos.cancel_draft(tenant_id=tenant_id, draft_id=draft_id, drafts=self._drafts)
        else:
            drafts_citas.cancel_draft(tenant_id=tenant_id, draft_id=draft_id, drafts=self._drafts)

    def undo(self, *, tenant_id: str, draft_id: str) -> None:
        """Deshace un draft ya commiteado dentro de su ventana.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft commiteado a deshacer.
        """
        draft = self._draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft.kind == "order":
            drafts_pedidos.undo_draft(
                tenant_id=tenant_id,
                draft_id=draft_id,
                legacy=self._legacy,
                drafts=self._drafts,
                clock=self._clock,
            )
        else:
            drafts_citas.undo_draft(
                tenant_id=tenant_id,
                draft_id=draft_id,
                repo=self._repo_citas,
                drafts=self._drafts,
                clock=self._clock,
            )

    def _draft(self, *, tenant_id: str, draft_id: str) -> PendingDraft:
        """Recupera el draft o lanza el error compartido por el router.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Identificador del draft.

        Returns:
            El draft del comercio.

        Raises:
            AppError: Si no existe en este comercio.
        """
        draft = self._drafts.get(tenant_id=tenant_id, draft_id=draft_id)
        if draft is None:
            raise ValidationError(
                "draft no encontrado en la consola",
                details={"draft_id": draft_id},
            )
        return draft


class ChatOutcome(BaseModel):
    """Resultado de un turno de la consola, listo para serializar en la API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reply: str | None = None
    intent: str | None = None
    confidence: float | None = None
    target: str | None = None
    route_error: str | None = None
    pending_outcome: str | None = None
    notice: str | None = None
    latency_ms: int = Field(ge=0)
    thread_id: str


@dataclass
class TenantRuntime:
    """Estado vivo de un comercio dentro de la consola.

    Los stores se crean una sola vez; al cambiar la configuración solo se recompila el
    grafo, de modo que las citas/pedidos ya creados siguen ahí.
    """

    profile: TenantProfile
    appointments: InMemoryAppointmentRepository
    orders: InMemoryOrderRepository
    drafts: InMemoryDraftStore
    legacy: InMemoryLegacyOrders
    catalog: InMemoryCatalog
    customer_context: InMemoryCustomerContextStore
    checkpointer: PortCheckpointSaver
    knowledge: InMemoryVectorStore
    llm: LLMPort
    graph: CompiledStateGraph[Any, Any, Any, Any] | None = None
    histories: dict[str, list[LLMMessage]] = field(default_factory=dict)


class ConsoleRuntime:
    """Composición y sesiones de la consola local.

    Args:
        service: Casos de uso de perfil y prompts.
        llm: LLM inyectado (tests); `None` selecciona fake/Bedrock según el entorno.
        llm_mode: `auto` (por defecto), `fake` o `bedrock`.
        bedrock_model_id: Modelo por defecto si el perfil no trae uno.
        bedrock_timeout_seconds: Timeout del cliente Bedrock.
    """

    def __init__(
        self,
        *,
        service: TenantConfigService,
        llm: LLMPort | None = None,
        llm_mode: LlmMode = "auto",
        bedrock_model_id: str | None = None,
        bedrock_timeout_seconds: int = 30,
    ) -> None:
        self._service = service
        self._runtimes: dict[str, TenantRuntime] = {}
        self._injected_llm = llm
        self._bedrock_model_id: str = (
            bedrock_model_id or os.getenv("CHATBOT_BEDROCK_MODEL_ID", "") or ""
        )
        self._bedrock_timeout_seconds = bedrock_timeout_seconds
        self._llm_mode, self.llm_warning = self._seleccionar_modo(
            llm_mode if llm is None else "fake"
        )
        self._fake_llm: LLMPort | None = llm if llm is not None else None
        self._clock = _RelojLocal()

    @property
    def llm_mode(self) -> str:
        """Modo efectivo del LLM (`fake` o `bedrock`)."""
        return self._llm_mode

    @property
    def service(self) -> TenantConfigService:
        """Casos de uso de perfil y prompts que usa el runtime."""
        return self._service

    def get(self, tenant_id: str) -> TenantRuntime:
        """Devuelve el runtime del comercio, construyéndolo o refrescándolo.

        Args:
            tenant_id: Comercio solicitado.

        Returns:
            Runtime con stores y grafo listos.

        Raises:
            TenantProfileNotFoundError: Si el comercio no existe en la consola.
        """
        profile = self._service.get_tenant(tenant_id)
        runtime = self._runtimes.get(tenant_id)
        if runtime is None:
            runtime = self._crear(profile)
            self._runtimes[tenant_id] = runtime
            return runtime
        if runtime.profile != profile:
            self._refrescar(runtime, profile)
        return runtime

    def chat(
        self,
        *,
        tenant_id: str,
        session_id: str,
        message: str,
        customer_id: str = _CLIENTE_DEMO,
    ) -> ChatOutcome:
        """Ejecuta un turno simulado y devuelve respuesta + traza.

        Args:
            tenant_id: Comercio de la conversación.
            session_id: Identificador de la sesión de la consola (sin `#`).
            message: Texto del cliente simulado.
            customer_id: Cliente simulado (clave del contexto y de los drafts).

        Returns:
            `ChatOutcome` con la respuesta y los campos de traza disponibles.

        Raises:
            ValidationError: Si el mensaje o la sesión están vacíos o la sesión contiene
                el separador `#` del `thread_id`.
        """
        texto = message.strip()
        if not texto:
            raise ValidationError("el mensaje no puede estar vacío")
        if not session_id or "#" in session_id:
            raise ValidationError(
                "session_id inválido para la consola",
                details={"session_id": session_id},
            )
        runtime = self.get(tenant_id)
        thread_id = thread_id_de(
            tenant_id=tenant_id,
            conversation_id=f"console:{session_id}",
        )
        historial = runtime.histories.setdefault(thread_id, [])
        entrada = InboundMessage(
            tenant_id=tenant_id,
            correlation_id=uuid.uuid4().hex,
            channel="whatsapp",
            emitter_id="console",
            customer_id=customer_id,
            message_id=uuid.uuid4().hex,
            timestamp=datetime.now(),
            text=texto,
        )
        if runtime.graph is None:
            raise AppError("el grafo de la consola no está compilado")
        inicio = time.perf_counter()
        resultado: dict[str, Any] = runtime.graph.invoke(
            {"message": entrada, "history": list(historial)},
            config={"configurable": {"thread_id": thread_id}},
        )
        latencia = int((time.perf_counter() - inicio) * 1000)
        reply = resultado.get("reply")
        texto_reply = reply if isinstance(reply, str) and reply else None
        historial.append(LLMMessage(role="user", content=texto))
        if texto_reply:
            historial.append(LLMMessage(role="assistant", content=texto_reply))
        routed = resultado.get("routed")
        target = resultado.get("target") or getattr(routed, "target", None)
        route_error = resultado.get("route_error")
        notice: str | None = None
        if route_error:
            notice = f"El turno no se pudo enrutar: {route_error}."
        elif texto_reply is None and target:
            notice = (
                f"Turno enrutado a «{target}», pero ese especialista no está "
                "configurado en la consola."
            )
        elif texto_reply is None:
            notice = "El turno terminó sin respuesta del especialista."
        return ChatOutcome(
            reply=texto_reply,
            intent=resultado.get("intent"),
            confidence=resultado.get("confidence"),
            target=target,
            route_error=route_error,
            pending_outcome=resultado.get("pending_outcome"),
            notice=notice,
            latency_ms=latencia,
            thread_id=thread_id,
        )

    def reset(self, *, tenant_id: str, session_id: str) -> None:
        """Borra el historial y el checkpoint de una sesión.

        Args:
            tenant_id: Comercio de la sesión.
            session_id: Sesión a reiniciar.

        Raises:
            ValidationError: Si falta la sesión o contiene `#`.
        """
        if not session_id or "#" in session_id:
            raise ValidationError(
                "session_id inválido para la consola",
                details={"session_id": session_id},
            )
        runtime = self.get(tenant_id)
        thread_id = thread_id_de(
            tenant_id=tenant_id,
            conversation_id=f"console:{session_id}",
        )
        runtime.checkpointer.delete_thread(thread_id)
        runtime.histories.pop(thread_id, None)

    def citas(self, tenant_id: str) -> list[Appointment]:
        """Lista las citas en memoria del comercio (para la traza/desarrollo).

        Args:
            tenant_id: Comercio consultado.

        Returns:
            Citas del periodo completo, ordenadas por inicio.
        """
        runtime = self.get(tenant_id)
        return list(
            runtime.appointments.list_for_period(
                tenant_id=tenant_id,
                start=datetime(2000, 1, 1),
                end=datetime(2100, 12, 31),
            )
        )

    def pedidos(self, tenant_id: str) -> list[Order]:
        """Lista los pedidos en memoria del comercio (para la traza/desarrollo).

        Args:
            tenant_id: Comercio consultado.

        Returns:
            Pedidos del comercio en orden de creación.
        """
        return self.get(tenant_id).orders.list_for_tenant(tenant_id=tenant_id)

    def _seleccionar_modo(self, solicitado: LlmMode) -> tuple[Literal["fake", "bedrock"], str]:
        """Decide con qué motor arranca la consola.

        Args:
            solicitado: Modo pedido por entorno o por constructor.

        Returns:
            Tupla `(modo efectivo, aviso)`; el aviso explica una caída a simulador.
        """
        modo = (os.getenv("CHATBOT_CONSOLE_LLM") or solicitado).lower()
        if modo == "fake":
            return "fake", "Modo simulador: las respuestas no reflejan el prompt."
        if not self._bedrock_model_id:
            return "fake", "Falta CHATBOT_BEDROCK_MODEL_ID; se usa el simulador."
        try:
            credenciales = boto3.Session().get_credentials()
        except BotoCoreError:
            credenciales = None
        if credenciales is None:
            return "fake", "No hay credenciales de AWS; se usa el simulador."
        if modo in ("auto", "bedrock"):
            return "bedrock", ""
        return "fake", f"Modo desconocido «{modo}»; se usa el simulador."

    def _llm_para(self, profile: TenantProfile) -> LLMPort:
        """Devuelve el LLM del comercio (fake inyectado o Bedrock por perfil).

        Args:
            profile: Perfil del comercio.

        Returns:
            El LLM ya listo para el grafo.
        """
        if self._injected_llm is not None:
            return self._injected_llm
        if self._llm_mode == "fake":
            if self._fake_llm is None:
                self._fake_llm = FakeLLM()
            return self._fake_llm
        modelo = profile.model_id or self._bedrock_model_id
        try:
            return BedrockLLM(
                model_id=modelo,
                timeout_seconds=self._bedrock_timeout_seconds,
            )
        except (NoRegionError, BotoCoreError) as exc:
            self._llm_mode = "fake"
            self.llm_warning = (
                "No se pudo inicializar Bedrock; se usa el simulador. "
                f"Detalle: {type(exc).__name__}."
            )
            if self._fake_llm is None:
                self._fake_llm = FakeLLM()
            return self._fake_llm

    def _crear(self, profile: TenantProfile) -> TenantRuntime:
        """Crea stores, checkpointer y grafo para un comercio nuevo.

        Args:
            profile: Perfil del comercio.

        Returns:
            Runtime listo para conversar.
        """
        drafts = InMemoryDraftStore(clock=self._clock)
        orders = InMemoryOrderRepository()
        appointments = InMemoryAppointmentRepository()
        legacy = InMemoryLegacyOrders(orders, clock=self._clock)
        conocimiento = InMemoryVectorStore()
        conocimiento.upsert(records=_conocimiento_demo(profile.tenant_id, profile.display_name))
        runtime = TenantRuntime(
            profile=profile,
            appointments=appointments,
            orders=orders,
            drafts=drafts,
            legacy=legacy,
            catalog=InMemoryCatalog(_productos_demo(profile.tenant_id)),
            customer_context=InMemoryCustomerContextStore(clock=self._clock),
            checkpointer=PortCheckpointSaver(
                store=InMemoryMemoryStore(),
                serde=JsonPlusSerializer(
                    allowed_msgpack_modules=[
                        ("shared.contracts.messages", "InboundMessage"),
                        ("shared.contracts.messages", "CustomerContext"),
                        ("shared.contracts.messages", "RoutedTurn"),
                        ("shared.contracts.pending", "PendingDraft"),
                        ("shared.ports.llm", "LLMMessage"),
                    ]
                ),
            ),
            knowledge=conocimiento,
            llm=self._llm_para(profile),
        )
        runtime.graph = self._compilar_grafo(runtime)
        logger.info(
            "console.tenant_runtime_created",
            extra={"tenant_id": profile.tenant_id, "llm_mode": self._llm_mode},
        )
        return runtime

    def _refrescar(self, runtime: TenantRuntime, profile: TenantProfile) -> None:
        """Recompila el grafo tras un cambio de perfil, conservando los stores.

        Args:
            runtime: Runtime existente del comercio.
            profile: Perfil nuevo.
        """
        nombre_cambio = runtime.profile.display_name != profile.display_name
        runtime.profile = profile
        if nombre_cambio:
            runtime.knowledge.upsert(
                records=_conocimiento_demo(profile.tenant_id, profile.display_name)
            )
        runtime.llm = self._llm_para(profile)
        runtime.graph = self._compilar_grafo(runtime)
        logger.info(
            "console.tenant_runtime_refreshed",
            extra={"tenant_id": profile.tenant_id},
        )

    def _compilar_grafo(self, runtime: TenantRuntime) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Construye el supervisor y sus especialistas con el perfil actual.

        Args:
            runtime: Stores y perfil del comercio.

        Returns:
            Grafo compilado listo para `invoke`.
        """
        profile = runtime.profile
        embeddings = InMemoryEmbeddings()
        citas = build_appointment_graph(
            llm=runtime.llm,
            repo=runtime.appointments,
            clock=self._clock,
            opening_hours=_HORARIO,
            drafts=runtime.drafts,
            allowed_tools=self._allowed_tools("appointments", profile),
            system_prompt=self._service.prompt_for(profile.tenant_id, "appointments"),
        )
        pedidos = build_order_graph(
            llm=runtime.llm,
            legacy=runtime.legacy,
            catalog=runtime.catalog,
            clock=self._clock,
            kitchen_hours=_COCINA,
            drafts=runtime.drafts,
            allowed_tools=self._allowed_tools("orders", profile),
            system_prompt=self._service.prompt_for(profile.tenant_id, "orders"),
        )
        faq = build_faq_graph(
            llm=runtime.llm,
            embeddings=embeddings,
            store=runtime.knowledge,
            threshold=0.12,  # demo local: el embedding de bolsa de palabras es débil
            system_prompt=self._service.prompt_for(profile.tenant_id, "faq"),
        )
        lector = CustomerContextTools(store=runtime.customer_context, clock=self._clock)
        confirmer = _Confirmer(
            drafts=runtime.drafts,
            legacy=runtime.legacy,
            repo_citas=runtime.appointments,
            clock=self._clock,
        )
        return build_supervisor_graph(
            llm=runtime.llm,
            context_reader=lector,
            allowed_bots=frozenset(profile.allowed_bots),
            appointments_graph=citas,
            orders_graph=pedidos,
            faq_graph=faq,
            draft_store=runtime.drafts,
            confirmer=confirmer,
            checkpointer=runtime.checkpointer,
            tenant_name=profile.display_name,
            system_prompt=self._service.prompt_for(profile.tenant_id, "supervisor"),
        )

    @staticmethod
    def _allowed_tools(bot: str, profile: TenantProfile) -> frozenset[Any] | None:
        """Deriva la allowlist fina de un especialista desde `allowed_bots`.

        Args:
            bot: Bot dueño del especialista (`appointments` u `orders`).
            profile: Perfil del comercio.

        Returns:
            `None` (toda la allowlist) si el bot está activo; `frozenset()` si no.
        """
        return None if bot in profile.allowed_bots else frozenset()


def build_default_service() -> TenantConfigService:
    """Compone el servicio de perfiles sobre `console-data/` (o la semilla).

    Returns:
        Servicio listo para la API y el runtime.
    """
    from pathlib import Path

    from slices.tenant_prompts.domain.entities import default_profile
    from slices.tenant_prompts.infrastructure.local_json import LocalJsonTenantRepository

    configurado = os.getenv("CHATBOT_CONSOLE_DATA_DIR")
    data_dir = (
        Path(configurado) if configurado else Path(__file__).resolve().parents[2] / "console-data"
    )
    repo = LocalJsonTenantRepository(
        data_dir / "tenants.json",
        seed=default_profile(_TENANT_DEMO),
    )
    return TenantConfigService(repository=repo)


def build_default_runtime() -> ConsoleRuntime:
    """Compone el runtime por defecto de la consola local.

    Returns:
        Runtime con el JSON de `console-data/` (o la semilla sintética) y el modo LLM
        que resuelva el entorno.
    """
    timeout = int(os.getenv("CHATBOT_BEDROCK_TIMEOUT_SECONDS", "30"))
    return ConsoleRuntime(
        service=build_default_service(),
        llm_mode="auto",
        bedrock_timeout_seconds=timeout,
    )
