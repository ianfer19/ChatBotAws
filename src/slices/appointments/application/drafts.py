"""Ciclo de vida de los drafts de citas: commit, confirmación, cancelación y deshacer.

Implementa la máquina de estados del ADR 0011 sobre `DraftStorePort`: el commit solo
sale desde `AUTO_APPROVED`/`CONFIRMED` (invariante exigida también por el store), la
ventana de deshacer revierte la escritura y la cancelación libera la ranura activa de
la conversación. Estas funciones son el único punto donde una propuesta se convierte
en datos reales; las llaman las tools (commit `AUTO`) y el router del supervisor
(confirmación del cliente, Paso 4/Fase 4).

`TODO(decision)`: TTL de confirmación (24 h) y ventana de deshacer (30 min) son
umbrales iniciales; se recalibran con métricas reales (Paso 13).
"""

import uuid
from datetime import datetime, timedelta

from shared.contracts.pending import COMMITIBLE_STATUSES, DraftStatus, PendingDraft
from shared.errors import ValidationError
from shared.ports import ClockPort, DraftStorePort
from slices.appointments.domain.entities import Appointment
from slices.appointments.domain.errors import (
    DraftNotCommittable,
    DraftNotFound,
    TenantMismatch,
)
from slices.appointments.domain.ports import AppointmentRepositoryPort

TTL_CONFIRMACION = timedelta(hours=24)
"""Cuánto tiempo espera un draft `AWAITING_CONFIRMATION` antes de expirar."""

VENTANA_DESHACER = timedelta(minutes=30)
"""Ventana tras un commit `AUTO` en la que el cliente puede deshacer la acción."""


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


def _ejecutar_payload(
    draft: PendingDraft, *, tenant_id: str, repo: AppointmentRepositoryPort
) -> Appointment:
    """Ejecuta la escritura que describe el payload del draft (commit efectivo).

    Args:
        draft: Draft en estado commiteable.
        tenant_id: Comercio bajo el que se escribe.
        repo: Repositorio de citas.

    Returns:
        La cita resultante (`confirmed` al crear, `cancelled` al cancelar).

    Raises:
        ValidationError: Si el `op` del payload no es reconocido.
        TenantMismatch: Si el `op` es cancelar y la cita no existe en este comercio.
    """
    operacion = draft.payload.get("op")
    if operacion == "create":
        appointment = Appointment(
            id=f"appt-{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            starts_at=datetime.fromisoformat(f"{draft.payload['date']}T{draft.payload['time']}"),
            customer_name=str(draft.payload["customer_name"]),
            contact=str(draft.payload["contact"]),
            status="confirmed",
            correlation_id=draft.correlation_id,
        )
        repo.save(tenant_id=tenant_id, appointment=appointment)
        return appointment
    if operacion == "cancel":
        appointment_id = str(draft.payload["appointment_id"])
        cita = repo.find(tenant_id=tenant_id, appointment_id=appointment_id)
        if cita is None:
            raise TenantMismatch(
                "cita a cancelar no encontrada en este comercio",
                details={"appointment_id": appointment_id},
            )
        cancelada = cita.model_copy(update={"status": "cancelled"})
        repo.save(tenant_id=tenant_id, appointment=cancelada)
        return cancelada
    raise ValidationError(
        "operación del draft desconocida",
        details={"draft_id": draft.draft_id, "op": str(operacion)},
    )


def commit_draft(
    *,
    tenant_id: str,
    draft_id: str,
    repo: AppointmentRepositoryPort,
    drafts: DraftStorePort,
    clock: ClockPort,
) -> Appointment:
    """Ejecuta el draft (solo desde `AUTO_APPROVED` o `CONFIRMED`) y lo marca `COMMITTED`.

    Args:
        tenant_id: Comercio dueño del draft (del contexto, nunca del LLM).
        draft_id: Draft a ejecutar.
        repo: Repositorio de citas donde se materializa la escritura.
        drafts: Store de drafts (impone la invariante de commit del ADR 0011.6).
        clock: Reloj para fijar la ventana de deshacer.

    Returns:
        La cita creada o cancelada por el payload del draft.

    Raises:
        DraftNotFound: Si el draft no existe en este comercio.
        DraftNotCommittable: Si el estado no es `AUTO_APPROVED`/`CONFIRMED`.
        TenantMismatch: Si el payload apunta a una cita ajena o `op` desconocida.
        ValidationError: Si la escritura rompe una regla del repositorio.
    """
    draft = _draft_o_fallo(drafts, tenant_id=tenant_id, draft_id=draft_id)
    _exigir_estado(draft, COMMITIBLE_STATUSES, "commit")
    appointment = _ejecutar_payload(draft, tenant_id=tenant_id, repo=repo)
    drafts.save(
        tenant_id=tenant_id,
        draft=draft.model_copy(
            update={
                "status": DraftStatus.COMMITTED,
                "undo_until": clock.now() + VENTANA_DESHACER,
            }
        ),
    )
    return appointment


def confirm_draft(
    *,
    tenant_id: str,
    draft_id: str,
    payload_hash: str,
    repo: AppointmentRepositoryPort,
    drafts: DraftStorePort,
    clock: ClockPort,
) -> Appointment:
    """Confirma un draft `AWAITING_CONFIRMATION` (verificando el hash) y lo commitea.

    El `payload_hash` es el enlace entre la confirmación del cliente y el contenido
    exacto propuesto (ADR 0011.2): un «sí» ligado a otro contenido no valida.

    Args:
        tenant_id: Comercio dueño del draft.
        draft_id: Draft a confirmar.
        payload_hash: Hash del contenido que el cliente confirmó.
        repo: Repositorio de citas.
        drafts: Store de drafts.
        clock: Reloj del turno.

    Returns:
        La cita creada o cancelada al ejecutar el draft.

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
        tenant_id=tenant_id, draft_id=draft_id, repo=repo, drafts=drafts, clock=clock
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
    repo: AppointmentRepositoryPort,
    drafts: DraftStorePort,
    clock: ClockPort,
) -> Appointment:
    """Deshace un commit dentro de su ventana de deshacer y cierra el draft.

    Args:
        tenant_id: Comercio dueño del draft.
        draft_id: Draft commiteado a deshacer.
        repo: Repositorio de citas (revierte la escritura).
        drafts: Store de drafts.
        clock: Reloj que compara contra `undo_until`.

    Returns:
        La cita en su estado previo al commit: `cancelled` si el draft creó la cita,
        `confirmed` si la canceló.

    Raises:
        DraftNotFound: Si el draft no existe en este comercio.
        DraftNotCommittable: Si no está `COMMITTED` o la ventana ya pasó.
        TenantMismatch: Si la cita del payload ya no existe en este comercio.
        ValidationError: Si el `op` del payload no es reconocido.
    """
    draft = _draft_o_fallo(drafts, tenant_id=tenant_id, draft_id=draft_id)
    _exigir_estado(draft, frozenset({DraftStatus.COMMITTED}), "undo")
    if draft.undo_until is None or draft.undo_until <= clock.now():
        raise DraftNotCommittable(
            "ventana de deshacer cerrada",
            details={"draft_id": draft_id},
        )
    operacion = draft.payload.get("op")
    if operacion == "create":
        appointment_id = _id_cita_creada(repo, tenant_id=tenant_id, draft=draft)
        cita = repo.find(tenant_id=tenant_id, appointment_id=appointment_id)
        if cita is None:
            raise TenantMismatch(
                "la cita creada por el draft ya no existe",
                details={"draft_id": draft_id},
            )
        revertida = cita.model_copy(update={"status": "cancelled"})
    elif operacion == "cancel":
        cita = repo.find(tenant_id=tenant_id, appointment_id=str(draft.payload["appointment_id"]))
        if cita is None:
            raise TenantMismatch(
                "la cita cancelada por el draft ya no existe",
                details={"draft_id": draft_id},
            )
        revertida = cita.model_copy(update={"status": "confirmed"})
    else:
        raise ValidationError(
            "operación del draft desconocida",
            details={"draft_id": draft_id, "op": str(operacion)},
        )
    repo.save(tenant_id=tenant_id, appointment=revertida)
    drafts.save(
        tenant_id=tenant_id, draft=draft.model_copy(update={"status": DraftStatus.CANCELLED})
    )
    return revertida


def _id_cita_creada(repo: AppointmentRepositoryPort, *, tenant_id: str, draft: PendingDraft) -> str:
    """Localiza la cita que creó el draft mediante su `correlation_id`.

    Args:
        repo: Repositorio de citas.
        tenant_id: Comercio dueño de la cita.
        draft: Draft commiteado con el `correlation_id` de la creación.

    Returns:
        Identificador de la cita creada.

    Raises:
        TenantMismatch: Si ya no existe ninguna cita con esa correlación.
    """
    if draft.correlation_id is None:
        raise TenantMismatch(
            "el draft de creación no tiene correlation_id",
            details={"draft_id": draft.draft_id},
        )
    cita = repo.find_by_correlation_id(tenant_id=tenant_id, correlation_id=draft.correlation_id)
    if cita is None:
        raise TenantMismatch(
            "la cita creada por el draft ya no existe",
            details={"draft_id": draft.draft_id},
        )
    return cita.id
