"""Ciclo de vida de los drafts de pedidos: commit, confirmación, cancelación y deshacer.

Implementa la máquina de estados del ADR 0011 sobre `DraftStorePort` (espejo de
`appointments/application/drafts.py`, con `kind="order"`): el commit solo sale desde
`AUTO_APPROVED`/`CONFIRMED`, la ventana de deshacer anula el pedido creado y la
cancelación libera la ranura activa de la conversación sin tocar el backend. Estas
funciones son el único punto donde una propuesta se convierte en datos reales; las
llaman las tools (commit `AUTO`) y el router del supervisor (confirmación del cliente,
Fase 4).

`TODO(decision)`: TTL de confirmación (24 h) y ventana de deshacer (30 min) son
umbrales iniciales; se recalibran con métricas reales (Paso 13).
"""

from datetime import timedelta

from shared.contracts.pending import COMMITIBLE_STATUSES, DraftStatus, PendingDraft
from shared.errors import ValidationError
from shared.ports import ClockPort, DraftStorePort
from slices.orders.domain.entities import Order, OrderItem
from slices.orders.domain.errors import DraftNotCommittable, DraftNotFound, OrderNotFound
from slices.orders.domain.ports import LegacyOrdersPort

TTL_CONFIRMACION = timedelta(hours=24)
"""Cuánto tiempo espera un draft `AWAITING_CONFIRMATION` antes de expirar."""

VENTANA_DESHACER = timedelta(minutes=30)
"""Ventana tras un commit `AUTO` en la que el cliente puede anular el pedido creado."""


def _draft_o_fallo(drafts: DraftStorePort, *, tenant_id: str, draft_id: str) -> PendingDraft:
    """Recupera un draft o lanza el error tipado correspondiente.

    Args:
        drafts: Store de drafts inyectado.
        tenant_id: Comercio dueño del draft.
        draft_id: Identificador del draft.

    Returns:
        El draft si existe en este comercio.

    Raises:
        DraftNotFound: Si no existe ningún draft con ese id en el comercio.
    """
    draft = drafts.get(tenant_id=tenant_id, draft_id=draft_id)
    if draft is None:
        raise DraftNotFound("draft no encontrado", details={"draft_id": draft_id})
    return draft


def _exigir_estado(draft: PendingDraft, permitidos: frozenset[DraftStatus], accion: str) -> None:
    """Valida que el draft esté en un estado que admita la transición pedida.

    Args:
        draft: Draft consultado.
        permitidos: Estados desde los que se admite la transición.
        accion: Nombre de la acción, para el detalle del error.

    Raises:
        DraftNotCommittable: Si el estado actual no admite la acción.
    """
    if draft.status not in permitidos:
        raise DraftNotCommittable(
            f"transición {accion} no permitida desde {draft.status}",
            details={"draft_id": draft.draft_id, "estado": draft.status.value},
        )


def _ejecutar_payload(draft: PendingDraft, *, tenant_id: str, legacy: LegacyOrdersPort) -> Order:
    """Ejecuta la escritura que describe el payload del draft (commit efectivo).

    Args:
        draft: Draft en estado commiteable.
        tenant_id: Comercio bajo el que se escribe.
        legacy: Backend legacy donde se registra el pedido.

    Returns:
        El pedido creado (siempre estado `ABIERTA` al abrir).

    Raises:
        ValidationError: Si el `op` del payload no es reconocido.
        LegacyTimeout: Si el backend no responde (contrato; hoy solo con HTTP real).
    """
    operacion = draft.payload.get("op")
    if operacion == "create":
        items = tuple(OrderItem.model_validate(linea) for linea in draft.payload.get("items", []))
        return legacy.create_order(
            tenant_id=tenant_id,
            correlation_id=draft.correlation_id or "",
            items=items,
            total=float(draft.payload.get("total", 0.0)),
        )
    raise ValidationError(
        "operación del draft desconocida",
        details={"draft_id": draft.draft_id, "op": str(operacion)},
    )


def commit_draft(
    *,
    tenant_id: str,
    draft_id: str,
    legacy: LegacyOrdersPort,
    drafts: DraftStorePort,
    clock: ClockPort,
) -> Order:
    """Ejecuta el draft (solo desde `AUTO_APPROVED` o `CONFIRMED`) y lo marca `COMMITTED`.

    Args:
        tenant_id: Comercio dueño del draft (del contexto, nunca del LLM).
        draft_id: Draft a ejecutar.
        legacy: Backend legacy donde se materializa el pedido.
        drafts: Store de drafts (impone la invariante de commit del ADR 0011.6).
        clock: Reloj para fijar la ventana de deshacer.

    Returns:
        El pedido creado por el payload del draft.

    Raises:
        DraftNotFound: Si el draft no existe en este comercio.
        DraftNotCommittable: Si el estado no es `AUTO_APPROVED`/`CONFIRMED`.
        ValidationError: Si el `op` del payload no es reconocido.
    """
    draft = _draft_o_fallo(drafts, tenant_id=tenant_id, draft_id=draft_id)
    _exigir_estado(draft, COMMITIBLE_STATUSES, "commit")
    pedido = _ejecutar_payload(draft, tenant_id=tenant_id, legacy=legacy)
    drafts.save(
        tenant_id=tenant_id,
        draft=draft.model_copy(
            update={
                "status": DraftStatus.COMMITTED,
                "undo_until": clock.now() + VENTANA_DESHACER,
            }
        ),
    )
    return pedido


def confirm_draft(
    *,
    tenant_id: str,
    draft_id: str,
    payload_hash: str,
    legacy: LegacyOrdersPort,
    drafts: DraftStorePort,
    clock: ClockPort,
) -> Order:
    """Confirma un draft `AWAITING_CONFIRMATION` (verificando el hash) y lo commitea.

    El `payload_hash` es el enlace entre la confirmación del cliente y el contenido
    exacto propuesto (ADR 0011.2): un «sí» ligado a otro contenido no valida.

    Args:
        tenant_id: Comercio dueño del draft.
        draft_id: Draft a confirmar.
        payload_hash: Hash del contenido que el cliente confirmó.
        legacy: Backend legacy.
        drafts: Store de drafts.
        clock: Reloj del turno.

    Returns:
        El pedido creado al ejecutar el draft.

    Raises:
        DraftNotFound: Si el draft no existe en este comercio.
        ValidationError: Si el hash no corresponde al payload actual.
        DraftNotCommittable: Si el draft no está `AWAITING_CONFIRMATION`.
    """
    draft = _draft_o_fallo(drafts, tenant_id=tenant_id, draft_id=draft_id)
    if draft.payload_hash != payload_hash:
        raise ValidationError(
            "el hash confirmado no corresponde al payload del draft",
            details={"draft_id": draft_id},
        )
    _exigir_estado(draft, frozenset({DraftStatus.AWAITING_CONFIRMATION}), "confirm")
    drafts.save(
        tenant_id=tenant_id, draft=draft.model_copy(update={"status": DraftStatus.CONFIRMED})
    )
    return commit_draft(
        tenant_id=tenant_id, draft_id=draft_id, legacy=legacy, drafts=drafts, clock=clock
    )


def cancel_draft(
    *,
    tenant_id: str,
    draft_id: str,
    drafts: DraftStorePort,
) -> PendingDraft:
    """Cancela un draft aún activo sin ejecutarlo («no, mejor luego» del cliente).

    Args:
        tenant_id: Comercio dueño del draft.
        draft_id: Draft a cancelar.
        drafts: Store de drafts.

    Returns:
        El draft resultante con estado `CANCELLED`.

    Raises:
        DraftNotFound: Si el draft no existe en este comercio.
        DraftNotCommittable: Si el draft ya no está activo (expirado o commiteado).
    """
    draft = _draft_o_fallo(drafts, tenant_id=tenant_id, draft_id=draft_id)
    _exigir_estado(
        draft,
        frozenset(
            {
                DraftStatus.DRAFTED,
                DraftStatus.AUTO_APPROVED,
                DraftStatus.AWAITING_CONFIRMATION,
                DraftStatus.CONFIRMED,
            }
        ),
        "cancel",
    )
    cancelado = draft.model_copy(update={"status": DraftStatus.CANCELLED})
    drafts.save(tenant_id=tenant_id, draft=cancelado)
    return cancelado


def undo_draft(
    *,
    tenant_id: str,
    draft_id: str,
    legacy: LegacyOrdersPort,
    drafts: DraftStorePort,
    clock: ClockPort,
) -> Order:
    """Anula dentro de su ventana el pedido creado por un commit `AUTO` (ADR 0011).

    Solo se deshacen pedidos aún `ABIERTA`: uno ya `CERRADA`/`ANULADA` no se toca
    (defensa: el estado real lo decide el backend, nunca el chatbot).

    Args:
        tenant_id: Comercio dueño del draft.
        draft_id: Draft commiteado a deshacer.
        legacy: Backend legacy (localiza y anula el pedido).
        drafts: Store de drafts.
        clock: Reloj que compara contra `undo_until`.

    Returns:
        El pedido con estado `ANULADA`.

    Raises:
        DraftNotFound: Si el draft no existe en este comercio.
        DraftNotCommittable: Si no está `COMMITTED`, la ventana ya pasó o el pedido
            ya no está `ABIERTA`.
        OrderNotFound: Si el pedido creado ya no existe en este comercio.
        ValidationError: Si el `op` del payload no es reconocido.
    """
    draft = _draft_o_fallo(drafts, tenant_id=tenant_id, draft_id=draft_id)
    _exigir_estado(draft, frozenset({DraftStatus.COMMITTED}), "undo")
    if draft.undo_until is None or draft.undo_until <= clock.now():
        raise DraftNotCommittable(
            "ventana de deshacer cerrada",
            details={"draft_id": draft_id},
        )
    if draft.payload.get("op") != "create":
        raise ValidationError(
            "operación del draft desconocida",
            details={"draft_id": draft_id, "op": str(draft.payload.get("op"))},
        )
    pedido = _pedido_creado(legacy, tenant_id=tenant_id, draft=draft)
    if pedido.status != "ABIERTA":
        raise DraftNotCommittable(
            "el pedido ya no está abierto para deshacer",
            details={"draft_id": draft_id, "estado": pedido.status},
        )
    revertido = legacy.void_order(tenant_id=tenant_id, order_id=pedido.id)
    drafts.save(
        tenant_id=tenant_id, draft=draft.model_copy(update={"status": DraftStatus.CANCELLED})
    )
    return revertido


def _pedido_creado(legacy: LegacyOrdersPort, *, tenant_id: str, draft: PendingDraft) -> Order:
    """Localiza el pedido que creó el draft mediante su `correlation_id`.

    Args:
        legacy: Backend legacy.
        tenant_id: Comercio dueño del pedido.
        draft: Draft commiteado con el `correlation_id` de la creación.

    Returns:
        El pedido creado.

    Raises:
        ValidationError: Si el draft no trae `correlation_id`.
        OrderNotFound: Si ya no existe ningún pedido con esa correlación.
    """
    if draft.correlation_id is None:
        raise ValidationError(
            "el draft de creación no tiene correlation_id",
            details={"draft_id": draft.draft_id},
        )
    pedido = legacy.find_by_correlation_id(tenant_id=tenant_id, correlation_id=draft.correlation_id)
    if pedido is None:
        raise OrderNotFound(
            "el pedido creado por el draft ya no existe",
            details={"draft_id": draft.draft_id},
        )
    return pedido
