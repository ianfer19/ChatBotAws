"""REPL de desarrollo para probar el supervisor con los especialistas de citas y pedidos.

Conversa por consola con el tenant indicado pasando por el supervisor real (Paso 4:
clasificación, saludo propio, contexto obligatorio y enrutado) con el router de
confirmación de drafts (Paso 5, ADR 0011: `draft_store` + `confirmer`) y ambos
especialistas compilados sobre `BedrockLLM` y dobles en memoria. La allowlist fina de
cada especialista se deriva de `allowed_bots` en esta composición. Sirve para ver un
turno completo sin desplegar nada. No es código de producción.

Desde el **Paso 8** la sesión lleva checkpointer (`PortCheckpointSaver` sobre un
`InMemoryMemoryStore`, hilo `tenant#whatsapp:cliente`): el resumen rodante y el estado
del turno sobreviven entre invocaciones y `/reset` borra el hilo completo. La ventana de
historial la aplica el grafo (`history_window_size`), no el script; en producción el
mismo port se apunta a DynamoDB (`CHATBOT_CHECKPOINTS_TABLE`).

Uso (PowerShell, desde la raíz del repo):

    $env:AWS_PROFILE = "iastock-old"
    $env:AWS_DEFAULT_REGION = "us-east-1"
    $env:CHATBOT_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    python scripts\\chat_citas.py                     # REPL interactivo
    python scripts\\chat_citas.py --turno "hola"       # un turno y sale (smoke local)
    python scripts\\chat_citas.py --tenant Otro --debug

Comandos del REPL: `/status` (sesión, hilo y citas creadas), `/reset` (borra la ventana
de historial y el checkpoint del hilo) y `/salir` (o Ctrl+D / Ctrl+C).
"""

import argparse
import logging
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

# El script se ejecuta sin instalar el paquete: añade `src` al path de importación.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from botocore.exceptions import NoRegionError
from langgraph.checkpoint.base import RunnableConfig
from pydantic import ValidationError as PydanticValidationError

from adapters.bedrock import BedrockLLM
from adapters.checkpointer import PortCheckpointSaver, thread_id_de
from adapters.in_memory import InMemoryDraftStore, InMemoryMemoryStore
from shared.config import load_settings
from shared.contracts import AgentName, InboundMessage
from shared.contracts.pending import PendingDraft
from shared.errors import AppError
from shared.logging import configure_logging
from shared.ports import ClockPort, LLMMessage
from slices.appointments.application import drafts as drafts_citas
from slices.appointments.application.graph import build_appointment_graph
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.application.schemas import ToolName as ToolNameCita
from slices.appointments.domain.entities import Appointment
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore
from slices.orders.application import drafts as drafts_pedidos
from slices.orders.application.graph import build_order_graph
from slices.orders.application.schemas import KitchenHoursDay
from slices.orders.application.schemas import ToolName as ToolNamePedido
from slices.orders.domain.entities import Order, Product
from slices.orders.domain.errors import DraftNotFound
from slices.orders.infrastructure.in_memory import (
    InMemoryCatalog,
    InMemoryLegacyOrders,
    InMemoryOrderRepository,
)
from slices.supervisor.application.graph import build_supervisor_graph

_TENANT_DEMO = "Sede_Elite_01"
_CLIENTE_DEMO = "57300111111"  # sintético: nunca datos reales de clientes en el repo
_CONVERSACION_DEMO = f"whatsapp:{_CLIENTE_DEMO}"
_SALIR = {"/salir", "/exit", "exit", "quit"}
# Horario de prueba (lun a vie, 9:00-18:00, hora local naive): el real llega con RAG (Paso 7).
_HORARIO: tuple[OpeningHoursDay, ...] = tuple(
    OpeningHoursDay(weekday=dia, open_time="09:00", close_time="18:00") for dia in range(5)
)
# Cocina siempre abierta en el REPL para que un turno de pedido funcione a cualquier
# hora; el horario real del comercio llega con RAG (Paso 7).
_COCINA: tuple[KitchenHoursDay, ...] = tuple(
    KitchenHoursDay(weekday=dia, open_time="00:00", close_time="23:59") for dia in range(7)
)
# Catálogo sintético del comercio demo (precios del doble; los reales los aporta el legacy).
_CATALOGO_DEMO: tuple[Product, ...] = (
    Product(
        tenant_id=_TENANT_DEMO,
        sku="A-100",
        name="Alitas BBQ",
        price=18_000,
        category="entradas",
    ),
    Product(
        tenant_id=_TENANT_DEMO,
        sku="P-100",
        name="Coca-Cola",
        price=5_000,
        category="bebidas",
    ),
)
_BOTS_DEMO: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
_AYUDA = (
    "Supervisor + citas + pedidos (Paso 5) sobre Bedrock. Comandos: /status, /reset, "
    "/salir (o Ctrl+D / Ctrl+C)."
)


class _RelojLocal:
    """`ClockPort` con la hora local del ordenador, naive como el horario demo."""

    def now(self) -> datetime:
        """Toma la hora actual del sistema sin zona horaria.

        Returns:
            `datetime.now()` naive; `TODO(decision)`: tz compartida con Aurora (Paso 6).
        """
        return datetime.now()


def _allowed_tools_de_citas(bots: frozenset[AgentName]) -> frozenset[ToolNameCita] | None:
    """Deriva la allowlist del especialista de citas desde los entitlements del comercio.

    Args:
        bots: `allowed_bots` del comercio.

    Returns:
        `None` (toda la allowlist del slice) si el bot `appointments` está activado;
        `frozenset()` —nada llega al modelo— en caso contrario (mínimo privilegio).
    """
    return None if "appointments" in bots else frozenset()


def _allowed_tools_de_pedidos(bots: frozenset[AgentName]) -> frozenset[ToolNamePedido] | None:
    """Deriva la allowlist del especialista de pedidos desde los entitlements del comercio.

    Args:
        bots: `allowed_bots` del comercio.

    Returns:
        `None` (toda la allowlist del slice) si el bot `orders` está activado;
        `frozenset()` —nada llega al modelo— en caso contrario (mínimo privilegio).
    """
    return None if "orders" in bots else frozenset()


class _ConfirmerLocal:
    """Implementación real del `ConfirmerPort` de este REPL (ADR 0011, composición).

    Despacha por el `kind` del draft al especialista dueño: `order` →
    `orders/application/drafts`, `appointment` → `appointments/application/drafts`.
    Comparte el mismo `InMemoryDraftStore` que los grafos, de modo que el router
    `resolve_pending` ve exactamente los drafts que crean las tools.
    """

    def __init__(
        self,
        *,
        drafts: InMemoryDraftStore,
        legacy: InMemoryLegacyOrders,
        repo_citas: InMemoryAppointmentRepository,
        clock: ClockPort,
    ) -> None:
        """Guarda las dependencias comunes que pide cada despacho.

        Args:
            drafts: Store compartido con los especialistas y con el router.
            legacy: Backend de pedidos en memoria (materializa los drafts de `order`).
            repo_citas: Repositorio de citas en memoria (materializa los de `appointment`).
            clock: Reloj para la ventana de deshacer.
        """
        self._drafts = drafts
        self._legacy = legacy
        self._repo_citas = repo_citas
        self._clock = clock

    def affirm(self, *, tenant_id: str, draft_id: str, payload_hash: str) -> None:
        """Confirma y ejecuta un draft `AWAITING_CONFIRMATION` de este comercio.

        Args:
            tenant_id: Comercio dueño del draft (siempre del contexto).
            draft_id: Draft a confirmar.
            payload_hash: Hash del contenido exacto que el cliente confirmó.

        Raises:
            DraftNotFound: Si no existe ningún draft con ese id en el comercio.
            DraftNotCommittable: Si el estado o el hash no admiten la transición.
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
        """Cancela un draft activo sin ejecutarlo («no» del cliente).

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft a cancelar.

        Raises:
            DraftNotFound: Si no existe ningún draft con ese id en el comercio.
            DraftNotCommittable: Si el draft ya no está activo.
        """
        draft = self._draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft.kind == "order":
            drafts_pedidos.cancel_draft(tenant_id=tenant_id, draft_id=draft_id, drafts=self._drafts)
        else:
            drafts_citas.cancel_draft(tenant_id=tenant_id, draft_id=draft_id, drafts=self._drafts)

    def undo(self, *, tenant_id: str, draft_id: str) -> None:
        """Deshace dentro de su ventana el draft ya commiteado («cancelar» tardío).

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft commiteado a deshacer.

        Raises:
            DraftNotFound: Si no existe ningún draft con ese id en el comercio.
            DraftNotCommittable: Si no está `COMMITTED` o la ventana ya pasó.
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
        """Recupera el draft o lanza el error tipado compartido por el router.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Identificador del draft.

        Returns:
            El draft si existe en este comercio.

        Raises:
            DraftNotFound: Si no existe; su `code` es `draft_not_found` en ambos
                especialistas, así que el router lo degrada igual.
        """
        draft = self._drafts.get(tenant_id=tenant_id, draft_id=draft_id)
        if draft is None:
            raise DraftNotFound("draft no encontrado", details={"draft_id": draft_id})
        return draft


class _Sesion:
    """Sesión de prueba: supervisor con Bedrock, historial, citas y pedidos en memoria."""

    def __init__(self, *, tenant: str) -> None:
        """Carga la configuración y compila el supervisor con sus dos especialistas.

        Comparte un único `InMemoryDraftStore` entre las tools, el router
        `resolve_pending` y el confirmer, y deriva la allowlist fina de cada
        especialista de `allowed_bots`. El checkpointer (Paso 8) persiste cada
        turno en un `InMemoryMemoryStore` bajo el hilo `tenant#conversación`.

        Args:
            tenant: Comercio simulado (el gateway lo resolverá en el Paso 9).

        Raises:
            PydanticValidationError: Si falta `CHATBOT_BEDROCK_MODEL_ID` (fail fast).
            NoRegionError: Si el entorno no define región de AWS.
            AppError: Si falta algún prompt base (citas, pedidos o supervisor).
        """
        settings = load_settings()
        self.tenant = tenant
        self.modelo = settings.bedrock_model_id
        self.historial: list[LLMMessage] = []
        self.turnos = 0
        self.hilo = thread_id_de(tenant_id=tenant, conversation_id=_CONVERSACION_DEMO)
        self._checkpointer = PortCheckpointSaver(store=InMemoryMemoryStore())
        self.repo = InMemoryAppointmentRepository()
        self.repo_pedidos = InMemoryOrderRepository()
        reloj = _RelojLocal()
        llm = BedrockLLM(
            model_id=settings.bedrock_model_id,
            timeout_seconds=settings.bedrock_timeout_seconds,
        )
        drafts = InMemoryDraftStore(clock=reloj)
        legacy = InMemoryLegacyOrders(self.repo_pedidos, clock=reloj)
        citas = build_appointment_graph(
            llm=llm,
            repo=self.repo,
            clock=reloj,
            opening_hours=_HORARIO,
            drafts=drafts,
            allowed_tools=_allowed_tools_de_citas(_BOTS_DEMO),
        )
        pedidos = build_order_graph(
            llm=llm,
            legacy=legacy,
            catalog=InMemoryCatalog(_CATALOGO_DEMO),
            clock=reloj,
            kitchen_hours=_COCINA,
            drafts=drafts,
            allowed_tools=_allowed_tools_de_pedidos(_BOTS_DEMO),
        )
        lector = CustomerContextTools(store=InMemoryCustomerContextStore(clock=reloj), clock=reloj)
        confirmer = _ConfirmerLocal(
            drafts=drafts,
            legacy=legacy,
            repo_citas=self.repo,
            clock=reloj,
        )
        self.grafo = build_supervisor_graph(
            llm=llm,
            context_reader=lector,
            allowed_bots=_BOTS_DEMO,
            appointments_graph=citas,
            orders_graph=pedidos,
            draft_store=drafts,
            confirmer=confirmer,
            checkpointer=self._checkpointer,
        )

    def turno(self, mensaje: str) -> dict[str, object]:
        """Ejecuta un turno por el supervisor con el hilo persistido.

        Args:
            mensaje: Texto del cliente para este turno.

        Returns:
            Estado final de LangGraph (`reply`, `routed`, `intent`, `route_error`...).
        """
        entrada = InboundMessage(
            tenant_id=self.tenant,
            correlation_id=uuid.uuid4().hex,
            channel="whatsapp",
            emitter_id="1000",
            customer_id=_CLIENTE_DEMO,
            message_id=uuid.uuid4().hex,
            timestamp=datetime.now(),
            text=mensaje,
        )
        config: RunnableConfig = {"configurable": {"thread_id": self.hilo}}
        resultado: dict[str, object] = self.grafo.invoke(
            {"message": entrada, "history": list(self.historial)},
            config=config,
        )
        reply = resultado.get("reply")
        self.historial.append(LLMMessage(role="user", content=mensaje))
        if isinstance(reply, str) and reply:
            self.historial.append(LLMMessage(role="assistant", content=reply))
        self.turnos += 1
        return resultado

    def citas(self) -> list[Appointment]:
        """Lista las citas del tenant en un periodo amplio (solo para depurar).

        Returns:
            Citas persistidas en memoria, ordenadas por inicio.
        """
        return list(
            self.repo.list_for_period(
                tenant_id=self.tenant,
                start=datetime(2000, 1, 1),
                end=datetime(2100, 12, 31),
            )
        )

    def pedidos(self) -> list[Order]:
        """Lista los pedidos del tenant creados en memoria (solo para depurar).

        Returns:
            Pedidos materializados por el doble legacy (commits `AUTO` o confirmados).
        """
        return self.repo_pedidos.list_for_tenant(tenant_id=self.tenant)

    def reiniciar(self) -> None:
        """Borra el historial y el checkpoint del hilo; las citas en memoria permanecen.

        El repositorio no se recrea: el grafo recibió el actual por DI al compilar,
        así que vaciarlo obligaría a tocar `src`.
        """
        self._checkpointer.delete_thread(self.hilo)
        self.historial.clear()
        self.turnos = 0


def _argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parsea la línea de comandos del script.

    Args:
        argv: Argumentos sin el nombre del programa (`None` = sys.argv).

    Returns:
        Namespace con `tenant`, `turno` y `debug`.
    """
    parser = argparse.ArgumentParser(
        description="REPL de pruebas del supervisor (y sus grafos) contra Amazon Bedrock."
    )
    parser.add_argument(
        "--tenant",
        default=_TENANT_DEMO,
        help="comercio simulado (default: %(default)s)",
    )
    parser.add_argument(
        "--turno",
        help="ejecuta un único turno con este texto y sale (smoke local)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="log DEBUG del adaptador y estado interno tras cada turno",
    )
    return parser.parse_args(argv)


def _imprimir_error(exc: AppError) -> None:
    """Vuelca un error tipado en consola sin stack trace.

    Args:
        exc: Excepción de `shared/errors` ya traducida por el sistema.
    """
    print(f"[{exc.code}] {exc.message}")
    if exc.details:
        print(f"  detalles: {exc.details}")
    causa = str(exc.__cause__) if exc.__cause__ is not None else ""
    if any(pista in causa for pista in ("credentials", "Operation not allowed", "being verified")):
        print("  pista: revisa AWS_PROFILE / AWS_DEFAULT_REGION o el acceso a modelos")


def _imprimir_turno(resultado: dict[str, object], *, debug: bool) -> None:
    """Muestra la respuesta o la ruta del turno y, si se pide, el estado interno.

    Args:
        resultado: Estado final devuelto por el grafo.
        debug: Si es `True`, imprime intención, destino y error de enrutado.
    """
    reply = resultado.get("reply")
    routed = resultado.get("routed")
    if isinstance(reply, str) and reply:
        print(f"\n{reply}\n")
    elif routed is not None:
        destino = getattr(routed, "target", "?")
        print(f"\n[enrutado a {destino}: agente especialista aún no implementado]\n")
    else:
        print("\n(sin respuesta)\n")
    if debug:
        print(
            "  [debug] "
            f"intencion={resultado.get('intent')} "
            f"confianza={resultado.get('confidence')} "
            f"destino={resultado.get('target')} "
            f"error_ruta={resultado.get('route_error')}"
        )


def _imprimir_status(sesion: _Sesion) -> None:
    """Imprime la sesión actual con las citas y los pedidos creados en memoria.

    Args:
        sesion: Sesión activa del REPL.
    """
    print(f"  tenant     : {sesion.tenant}")
    print(f"  modelo     : {sesion.modelo}")
    print(f"  turnos     : {sesion.turnos}")
    print(f"  hilo       : {sesion.hilo}")
    print(f"  historial  : {len(sesion.historial)} mensajes (la ventana la aplica el grafo)")
    citas = sesion.citas()
    if not citas:
        print("  citas      : ninguna en memoria")
    for cita in citas:
        print(f"    {cita.id}  {cita.starts_at.isoformat()}  {cita.status}  {cita.customer_name}")
    pedidos = sesion.pedidos()
    if not pedidos:
        print("  pedidos    : ninguno en memoria")
    for pedido in pedidos:
        print(
            f"    {pedido.id}  {pedido.status}  total {pedido.total:.0f}  "
            f"{len(pedido.items)} items"
        )


def _turno(sesion: _Sesion, mensaje: str, *, debug: bool) -> bool:
    """Ejecuta un turno e imprime su respuesta; los errores no rompen la sesión.

    Args:
        sesion: Sesión activa.
        mensaje: Texto del cliente.
        debug: Si es `True`, imprime también el estado interno.

    Returns:
        `True` si el turno terminó bien, `False` si la tool/LLM falló.
    """
    try:
        resultado = sesion.turno(mensaje)
    except AppError as exc:
        _imprimir_error(exc)
        return False
    _imprimir_turno(resultado, debug=debug)
    return True


def _repl(sesion: _Sesion, *, debug: bool) -> int:
    """Bucle interactivo: lee líneas, atiende comandos y ejecuta turnos.

    Args:
        sesion: Sesión ya construida por `main`.
        debug: Si es `True`, muestra el estado interno tras cada turno.

    Returns:
        Código de salida del proceso (0 siempre: los fallos de turno son no fatales).
    """
    print(_AYUDA)
    while True:
        try:
            linea = input("citas> ").strip()
            if not linea:
                continue
            if linea in _SALIR:
                return 0
            if linea == "/status":
                _imprimir_status(sesion)
                continue
            if linea == "/reset":
                sesion.reiniciar()
                print("historial y checkpoint del hilo borrados; las citas en memoria siguen")
                continue
            _turno(sesion, linea, debug=debug)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0


def _salida_consola_segura() -> None:
    """Evita que la consola Windows (cp1252) revienta con la redacción cruda del LLM.

    El modelo a veces responde con caracteres fuera de la codepage (p. ej. emojis):
    sin este ajuste, `print` lanza `UnicodeEncodeError` y mata el REPL a mitad de
    turno. Con `errors="replace"` lo no soportado sale como «?» y el turno sigue.
    """
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if callable(reconfigurar):
            reconfigurar(errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada: configura el entorno y arranca el REPL o un turno único.

    Args:
        argv: Argumentos de línea de comandos (`None` = sys.argv).

    Returns:
        0 si todo fue bien, 2 si falta configuración (modelo/región de AWS),
        1 si la sesión no se pudo construir.
    """
    _salida_consola_segura()
    args = _argumentos(argv)
    if args.debug:
        configure_logging("DEBUG")
        # El DEBUG de botocore/urllib3 no aporta: solo se quiere la traza del sistema.
        logging.getLogger("botocore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        sesion = _Sesion(tenant=str(args.tenant))
    except PydanticValidationError:
        print("Falta el modelo: define CHATBOT_BEDROCK_MODEL_ID (ver tests/integration/README.md)")
        return 2
    except NoRegionError:
        print("Falta la región de AWS: define AWS_DEFAULT_REGION=us-east-1")
        return 2
    except AppError as exc:
        _imprimir_error(exc)
        return 1

    if args.turno:
        return 0 if _turno(sesion, str(args.turno), debug=bool(args.debug)) else 1
    return _repl(sesion, debug=bool(args.debug))


if __name__ == "__main__":
    sys.exit(main())
