"""Tests del ciclo de vida de los drafts de pedidos: commit, confirm y deshacer (ADR 0011)."""

from datetime import datetime, timedelta

import pytest

from adapters.in_memory import InMemoryDraftStore
from shared.contracts.pending import DraftStatus, PendingDraft, compute_payload_hash
from shared.errors import ValidationError
from slices.orders.application.drafts import (
    cancel_draft,
    commit_draft,
    confirm_draft,
    undo_draft,
)
from slices.orders.application.schemas import KitchenHoursDay
from slices.orders.application.tools import OrderTools
from slices.orders.domain.entities import OrderItem, Product
from slices.orders.domain.errors import DraftNotCommittable, DraftNotFound
from slices.orders.infrastructure.in_memory import (
    InMemoryCatalog,
    InMemoryLegacyOrders,
    InMemoryOrderRepository,
)

TENANT = "Sede_Elite_01"
CONVERSACION = "whatsapp:57300111111"
COCINA_LUNES = KitchenHoursDay(weekday=0, open_time="11:00", close_time="15:00")
# Mensaje con los nombres literales: la política puede ir a `AUTO`.
_MSG_EXPLICITA = "quiero Alitas BBQ y una Coca-Cola"

_CATALOGO = InMemoryCatalog(
    [
        Product(tenant_id=TENANT, sku="A-100", name="Alitas BBQ", price=18_000),
        Product(tenant_id=TENANT, sku="P-100", name="Coca-Cola", price=5_000),
    ]
)


class _RelojMovil:
    """Reloj que arranca fijo y puede avanzarse para cruzar ventanas de tiempo."""

    def __init__(self, ahora: datetime) -> None:
        """Fija el instante inicial.

        Args:
            ahora: Instante de arranque.
        """
        self.ahora = ahora

    def now(self) -> datetime:
        """Devuelve el instante actual (avanzable con `avanzar`).

        Returns:
            El instante del reloj.
        """
        return self.ahora

    def avanzar(self, minutos: int) -> None:
        """Mueve el reloj hacia delante.

        Args:
            minutos: Minutos a sumar.
        """
        self.ahora = self.ahora + timedelta(minutes=minutos)


def _escenario() -> (
    tuple[
        OrderTools, InMemoryLegacyOrders, InMemoryOrderRepository, InMemoryDraftStore, _RelojMovil
    ]
):
    """Monta tools, legacy, repositorio, store y reloj móvil del test.

    Returns:
        Tupla con las cinco piezas ya cableadas entre sí.
    """
    reloj = _RelojMovil(datetime(2026, 3, 2, 12, 0))
    repo = InMemoryOrderRepository()
    legacy = InMemoryLegacyOrders(repo, clock=reloj)
    drafts = InMemoryDraftStore(clock=reloj)
    tools = OrderTools(
        legacy=legacy,
        catalog=_CATALOGO,
        drafts=drafts,
        clock=reloj,
        kitchen_hours=(COCINA_LUNES,),
        minimum=1_000,
    )
    return tools, legacy, repo, drafts, reloj


def _crear_pedido_auto(tools: OrderTools, *, correlation_id: str = "corr-auto") -> str:
    """Propone y commitea un pedido con política `AUTO`.

    Args:
        tools: Tools bajo prueba.
        correlation_id: Idempotencia de la propuesta.

    Returns:
        El `draft_id` del draft commiteado.
    """
    result = tools.propose_order(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        conversation_id=CONVERSACION,
        message=_MSG_EXPLICITA,
        items=(OrderItem(sku="A-100", quantity=2),),
    )
    assert result.draft_id is not None
    return result.draft_id


def _proponer_pendiente(tools: OrderTools, *, correlation_id: str = "corr-1") -> str:
    """Crea un draft `AWAITING_CONFIRMATION` y devuelve su id.

    Args:
        tools: Tools bajo prueba.
        correlation_id: Idempotencia de la propuesta.

    Returns:
        Identificador del draft a la espera de confirmación.
    """
    result = tools.propose_order(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        conversation_id=CONVERSACION,
        message="quiero pedir algo para la tarde",
        items=(
            OrderItem(sku="A-100", quantity=2),
            OrderItem(sku="P-100", quantity=1),
        ),
    )
    assert result.draft_id is not None
    return result.draft_id


def test_confirmar_draft_ejecuta_el_pedido() -> None:
    """El confirm del router exige el hash y materializa el pedido en el legacy."""
    tools, legacy, repo, drafts, reloj = _escenario()
    draft_id = _proponer_pendiente(tools)
    draft = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert draft is not None
    pedido = confirm_draft(
        tenant_id=TENANT,
        draft_id=draft_id,
        payload_hash=draft.payload_hash,
        legacy=legacy,
        drafts=drafts,
        clock=reloj,
    )
    assert pedido.status == "ABIERTA"
    guardado = repo.find(tenant_id=TENANT, order_id=pedido.id)
    assert guardado is not None
    tras_confirmar = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert tras_confirmar is not None and tras_confirmar.status is DraftStatus.COMMITTED


def test_confirmar_con_el_hash_desfasado_no_valida() -> None:
    """Un «sí» ligado a otro contenido no confirma nada (ADR 0011.2)."""
    tools, legacy, repo, drafts, reloj = _escenario()
    draft_id = _proponer_pendiente(tools)
    with pytest.raises(ValidationError):
        confirm_draft(
            tenant_id=TENANT,
            draft_id=draft_id,
            payload_hash="a" * 64,
            legacy=legacy,
            drafts=drafts,
            clock=reloj,
        )
    sin_confirmar = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert sin_confirmar is not None
    assert sin_confirmar.status is DraftStatus.AWAITING_CONFIRMATION
    assert repo.list_for_tenant(tenant_id=TENANT) == []


def test_commit_inexistente_y_desde_estado_invalido_se_rechazan() -> None:
    """La defensa en profundidad del commit: solo desde `AUTO_APPROVED`/`CONFIRMED`."""
    tools, legacy, repo, drafts, reloj = _escenario()
    with pytest.raises(DraftNotFound):
        commit_draft(
            tenant_id=TENANT,
            draft_id="drf-no-existe",
            legacy=legacy,
            drafts=drafts,
            clock=reloj,
        )
    payload = {
        "op": "create",
        "items": [{"sku": "A-100", "quantity": 2}],
        "total": 36_000,
    }
    draft = PendingDraft(
        draft_id="drf-drafted",
        tenant_id=TENANT,
        conversation_id=CONVERSACION,
        kind="order",
        status=DraftStatus.DRAFTED,
        payload=payload,
        payload_hash=compute_payload_hash(payload),
        correlation_id="corr-drafted",
        created_at=reloj.now(),
        expires_at=reloj.now().replace(hour=23),
    )
    drafts.save(tenant_id=TENANT, draft=draft)
    with pytest.raises(DraftNotCommittable):
        commit_draft(
            tenant_id=TENANT,
            draft_id="drf-drafted",
            legacy=legacy,
            drafts=drafts,
            clock=reloj,
        )
    assert repo.list_for_tenant(tenant_id=TENANT) == []


def test_cancelar_draft_libera_la_ranura_de_la_conversacion() -> None:
    """Cancelar el draft lo saca de activos y no escribe nada en el legacy."""
    tools, _, repo, drafts, _ = _escenario()
    draft_id = _proponer_pendiente(tools)
    cancelado = cancel_draft(tenant_id=TENANT, draft_id=draft_id, drafts=drafts)
    assert cancelado.status is DraftStatus.CANCELLED
    assert drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION) is None
    assert repo.list_for_tenant(tenant_id=TENANT) == []


def test_cancelar_un_draft_ya_commiteado_no_se_puede() -> None:
    """Un draft ejecutado no admite la transición «cancelar draft»."""
    tools, _, _, drafts, _ = _escenario()
    draft_id = _crear_pedido_auto(tools)
    with pytest.raises(DraftNotCommittable):
        cancel_draft(tenant_id=TENANT, draft_id=draft_id, drafts=drafts)


def test_deshacer_un_pedido_creado_lo_anula_y_cierra_el_draft() -> None:
    """Dentro de la ventana, deshacer anula el pedido y cierra el draft."""
    tools, legacy, repo, drafts, reloj = _escenario()
    draft_id = _crear_pedido_auto(tools)
    revertido = undo_draft(
        tenant_id=TENANT, draft_id=draft_id, legacy=legacy, drafts=drafts, clock=reloj
    )
    assert revertido.status == "ANULADA"
    guardado = repo.find_by_correlation_id(tenant_id=TENANT, correlation_id="corr-auto")
    assert guardado is not None and guardado.status == "ANULADA"
    tras_undo = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert tras_undo is not None and tras_undo.status is DraftStatus.CANCELLED


def test_deshacer_fuera_de_la_ventana_no_se_puede() -> None:
    """Pasados los 30 minutos el commit ya no admite deshacer."""
    tools, legacy, _, drafts, reloj = _escenario()
    draft_id = _crear_pedido_auto(tools)
    reloj.avanzar(31)
    with pytest.raises(DraftNotCommittable):
        undo_draft(
            tenant_id=TENANT,
            draft_id=draft_id,
            legacy=legacy,
            drafts=drafts,
            clock=reloj,
        )


def test_deshacer_un_pedido_ya_cerrado_no_se_puede() -> None:
    """Si el backend ya cerró el pedido, la ventana de deshacer no lo toca."""
    tools, legacy, repo, drafts, reloj = _escenario()
    draft_id = _crear_pedido_auto(tools)
    pedido = repo.find_by_correlation_id(tenant_id=TENANT, correlation_id="corr-auto")
    assert pedido is not None
    repo.save(tenant_id=TENANT, order=pedido.model_copy(update={"status": "CERRADA"}))
    with pytest.raises(DraftNotCommittable):
        undo_draft(
            tenant_id=TENANT,
            draft_id=draft_id,
            legacy=legacy,
            drafts=drafts,
            clock=reloj,
        )
