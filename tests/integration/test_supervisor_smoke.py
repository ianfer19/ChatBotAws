"""Smoke real del supervisor (Pasos 4 y 5): LangGraph + `BedrockLLM` contra Bedrock.

Tres turnos con las dependencias de producción (modelo real, lector de contexto real,
ambos especialistas reales): un saludo, que debe quedarse en el supervisor; una petición
de cita y un pedido, que deben invocar a su especialista. Verifica el camino completo
`load_context` → `resolve_pending` → `classify` → `decide` → [greet |
route_appointments | route_orders]. Son varias llamadas al modelo por turno
`TODO(verify pricing)` (Paso 14).

Se omite en CI o sin `CHATBOT_BEDROCK_MODEL_ID` real; si la cuenta aún no tiene
verificado el acceso a Bedrock, se omite con ese motivo en vez de fallar.
"""

from datetime import datetime
from typing import Any

import pytest
from _aws import (  # pyrefly: ignore[missing-import]
    MODELO_BEDROCK,
    es_acceso_pendiente,
    hay_credenciales,
)
from botocore.exceptions import NoRegionError

from adapters.bedrock import BedrockLLM
from adapters.in_memory import InMemoryDraftStore
from shared.config import load_settings
from shared.contracts import AgentName, InboundMessage
from shared.errors import ToolError
from slices.appointments.application.graph import build_appointment_graph
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore
from slices.orders.application.graph import build_order_graph
from slices.orders.application.schemas import KitchenHoursDay
from slices.orders.domain.entities import Product
from slices.orders.infrastructure.in_memory import (
    InMemoryCatalog,
    InMemoryLegacyOrders,
    InMemoryOrderRepository,
)
from slices.supervisor.application.graph import build_supervisor_graph

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not MODELO_BEDROCK, reason="sin CHATBOT_BEDROCK_MODEL_ID real en el entorno"
    ),
    pytest.mark.skipif(
        not hay_credenciales(), reason="sin credenciales AWS: el smoke test se omite en CI"
    ),
]

_TENANT = "Sede_Elite_01"
_CLIENTE = "57300111111"
_BOTS: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
_HORARIO = (OpeningHoursDay(weekday=0, open_time="09:00", close_time="18:00"),)
_COCINA = tuple(
    KitchenHoursDay(weekday=dia, open_time="00:00", close_time="23:59") for dia in range(7)
)
_CATALOGO = (
    Product(tenant_id=_TENANT, sku="A-100", name="Alitas BBQ", price=18_000, category="entradas"),
    Product(tenant_id=_TENANT, sku="P-100", name="Coca-Cola", price=5_000, category="bebidas"),
)
_MENSAJE_ID = "smoke-pasos-4-5"


class _RelojFijo:
    """Reloj fijo para que fecha y disponibilidad del smoke sean estables."""

    def now(self) -> datetime:
        """Instante fijo del smoke (lunes 2026-03-02, 08:00 local naive).

        Returns:
            La hora fija configurada.
        """
        return datetime(2026, 3, 2, 8, 0)


def _grafo() -> Any:
    """Compone el supervisor con el lector de contexto y los dos especialistas reales.

    Returns:
        El grafo del supervisor compilado con Bedrock por debajo.

    Raises:
        NoRegionError: Si el entorno no define región de AWS.
    """
    settings = load_settings()
    try:
        llm = BedrockLLM(
            model_id=settings.bedrock_model_id,
            timeout_seconds=settings.bedrock_timeout_seconds,
        )
    except NoRegionError:
        pytest.skip("sin región de AWS: define AWS_DEFAULT_REGION (p. ej. us-east-1)")
    reloj = _RelojFijo()
    drafts = InMemoryDraftStore(clock=reloj)
    lector = CustomerContextTools(store=InMemoryCustomerContextStore(clock=reloj), clock=reloj)
    citas = build_appointment_graph(
        llm=llm,
        repo=InMemoryAppointmentRepository(),
        clock=reloj,
        opening_hours=_HORARIO,
        drafts=drafts,
    )
    pedidos = build_order_graph(
        llm=llm,
        legacy=InMemoryLegacyOrders(InMemoryOrderRepository(), clock=reloj),
        catalog=InMemoryCatalog(_CATALOGO),
        clock=reloj,
        kitchen_hours=_COCINA,
        drafts=drafts,
    )
    return build_supervisor_graph(
        llm=llm,
        context_reader=lector,
        allowed_bots=_BOTS,
        appointments_graph=citas,
        orders_graph=pedidos,
    )


def _turno(texto: str) -> dict[str, object]:
    """Turno inicial con la ventana de historial presente (obligatoria, 7.2).

    Args:
        texto: Mensaje del cliente para el smoke.

    Returns:
        Estado inicial del grafo del supervisor.
    """
    return {
        "message": InboundMessage(
            tenant_id=_TENANT,
            correlation_id=_MENSAJE_ID,
            channel="whatsapp",
            customer_id=_CLIENTE,
            message_id=_MENSAJE_ID,
            timestamp=datetime(2026, 3, 2, 8, 0),
            text=texto,
        ),
        "history": [],
    }


def _invocar(grafo: Any, texto: str) -> Any:
    """Invoca un turno y omite el test si la cuenta aún no tiene acceso a modelos.

    Args:
        grafo: Grafo del supervisor compilado.
        texto: Mensaje del cliente.

    Returns:
        Estado final del turno.
    """
    try:
        return grafo.invoke(_turno(texto))
    except ToolError as exc:
        if es_acceso_pendiente(exc):
            pytest.skip("la cuenta AWS aún no tiene verificado el acceso a modelos de Bedrock")
        raise


def test_supervisor_saluda_sin_salir_de_su_ruta() -> None:
    """Con el modelo real, «hola» se queda en el supervisor: saludo propio, sin enrutado."""
    estado = _invocar(_grafo(), "hola")
    reply = estado.get("reply")
    assert isinstance(reply, str) and reply.strip()
    assert reply.startswith("Buenas")
    assert estado.get("target") == "supervisor"
    assert estado.get("routed") is None


def test_supervisor_enruta_una_cita_al_especialista() -> None:
    """Con el modelo real, una petición de cita invoca al especialista y responde."""
    estado = _invocar(_grafo(), "Quiero una cita el viernes a las 10 de la mañana")
    reply = estado.get("reply")
    assert isinstance(reply, str) and reply.strip()
    routed = estado.get("routed")
    assert routed is not None
    assert routed.target == "appointments"
    assert routed.message.tenant_id == _TENANT
    assert routed.message.correlation_id == _MENSAJE_ID


def test_supervisor_enruta_un_pedido_al_especialista() -> None:
    """Con el modelo real, un pedido invoca al especialista de pedidos y responde.

    El especialista real decide la tool (búsqueda o propuesta) con el catálogo en
    memoria; lo que se verifica aquí es el camino `route_orders` con Bedrock por
    debajo, no la elección concreta del modelo.
    """
    estado = _invocar(_grafo(), "Quiero pedir unas alitas BBQ para llevar")
    reply = estado.get("reply")
    assert isinstance(reply, str) and reply.strip()
    routed = estado.get("routed")
    assert routed is not None
    assert routed.target == "orders"
    assert routed.message.tenant_id == _TENANT
    assert routed.message.correlation_id == _MENSAJE_ID
