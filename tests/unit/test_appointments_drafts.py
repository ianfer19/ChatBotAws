"""Tests del ciclo de vida de los drafts de citas: commit, confirm y deshacer (ADR 0011)."""

from datetime import datetime, timedelta

import pytest

from adapters.in_memory import InMemoryDraftStore
from shared.contracts.pending import DraftStatus, PendingDraft, compute_payload_hash
from shared.errors import ValidationError
from slices.appointments.application.drafts import (
    cancel_draft,
    commit_draft,
    confirm_draft,
    undo_draft,
)
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.application.tools import AppointmentTools
from slices.appointments.domain.errors import DraftNotCommittable, DraftNotFound
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository

TENANT = "Sede_Elite_01"
CONVERSACION = "whatsapp:57300111111"
LUNES = OpeningHoursDay(weekday=0, open_time="09:00", close_time="12:00")


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
    tuple[AppointmentTools, InMemoryAppointmentRepository, InMemoryDraftStore, _RelojMovil]
):
    """Monta tools, repositorio, store y reloj móvil del test.

    Returns:
        Tupla con las cuatro piezas ya cableadas entre sí.
    """
    reloj = _RelojMovil(datetime(2026, 3, 2, 8, 0))
    repo = InMemoryAppointmentRepository()
    drafts = InMemoryDraftStore(clock=reloj)
    tools = AppointmentTools(repo=repo, clock=reloj, opening_hours=(LUNES,), drafts=drafts)
    return tools, repo, drafts, reloj


def _crear_cita_auto(tools: AppointmentTools, *, correlation_id: str = "corr-auto") -> str:
    """Propone y commitea una cita con política `AUTO`.

    Args:
        tools: Tools bajo prueba.
        correlation_id: Idempotencia de la propuesta.

    Returns:
        El `draft_id` del draft commiteado.
    """
    result = tools.propose_appointment(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        conversation_id=CONVERSACION,
        message="cita 2026-03-02 10:00 Ana Pérez 3001112233",
        date="2026-03-02",
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )
    assert result.draft_id is not None
    return result.draft_id


def _proponer_pendiente(tools: AppointmentTools, *, correlation_id: str = "corr-1") -> str:
    """Crea un draft `AWAITING_CONFIRMATION` y devuelve su id.

    Args:
        tools: Tools bajo prueba.
        correlation_id: Idempotencia de la propuesta.

    Returns:
        Identificador del draft a la espera de confirmación.
    """
    result = tools.propose_appointment(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        conversation_id=CONVERSACION,
        message="quiero cita el lunes a las 10 con Ana",
        date="2026-03-02",
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )
    assert result.draft_id is not None
    return result.draft_id


def test_confirmar_draft_ejecuta_la_cita() -> None:
    """El confirm del router exige el hash y materializa la escritura."""
    tools, repo, drafts, reloj = _escenario()
    draft_id = _proponer_pendiente(tools)
    draft = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert draft is not None
    cita = confirm_draft(
        tenant_id=TENANT,
        draft_id=draft_id,
        payload_hash=draft.payload_hash,
        repo=repo,
        drafts=drafts,
        clock=reloj,
    )
    assert cita.status == "confirmed"
    guardada = repo.find(tenant_id=TENANT, appointment_id=cita.id)
    assert guardada is not None
    tras_confirmar = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert tras_confirmar is not None and tras_confirmar.status is DraftStatus.COMMITTED


def test_confirmar_con_el_hash_desfasado_no_valida() -> None:
    """Un «sí» ligado a otro contenido no confirma nada (ADR 0011.2)."""
    tools, repo, drafts, reloj = _escenario()
    draft_id = _proponer_pendiente(tools)
    with pytest.raises(ValidationError):
        confirm_draft(
            tenant_id=TENANT,
            draft_id=draft_id,
            payload_hash="a" * 64,
            repo=repo,
            drafts=drafts,
            clock=reloj,
        )
    sin_confirmar = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert sin_confirmar is not None
    assert sin_confirmar.status is DraftStatus.AWAITING_CONFIRMATION
    assert (
        repo.list_for_period(
            tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
        )
        == []
    )


def test_commit_inexistente_y_desde_estado_invalido_se_rechazan() -> None:
    """La defensa en profundidad del commit: solo desde `AUTO_APPROVED`/`CONFIRMED`."""
    tools, repo, drafts, reloj = _escenario()
    with pytest.raises(DraftNotFound):
        commit_draft(
            tenant_id=TENANT,
            draft_id="drf-no-existe",
            repo=repo,
            drafts=drafts,
            clock=reloj,
        )
    payload = {
        "op": "create",
        "date": "2026-03-02",
        "time": "10:00",
        "customer_name": "Ana Pérez",
        "contact": "3001112233",
    }
    draft = PendingDraft(
        draft_id="drf-drafted",
        tenant_id=TENANT,
        conversation_id=CONVERSACION,
        kind="appointment",
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
            repo=repo,
            drafts=drafts,
            clock=reloj,
        )


def test_cancelar_draft_libera_la_ranura_de_la_conversacion() -> None:
    """Cancelar el draft lo saca de activos y no escribe nada en el repositorio."""
    tools, repo, drafts, _ = _escenario()
    draft_id = _proponer_pendiente(tools)
    cancelado = cancel_draft(tenant_id=TENANT, draft_id=draft_id, drafts=drafts)
    assert cancelado.status is DraftStatus.CANCELLED
    assert drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION) is None
    assert (
        repo.list_for_period(
            tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
        )
        == []
    )


def test_cancelar_un_draft_ya_commiteado_no_se_puede() -> None:
    """Un draft ejecutado no admite la transición «cancelar draft»."""
    tools, _, drafts, _ = _escenario()
    draft_id = _crear_cita_auto(tools)
    with pytest.raises(DraftNotCommittable):
        cancel_draft(tenant_id=TENANT, draft_id=draft_id, drafts=drafts)


def test_deshacer_una_cita_creada_la_cancela_y_cierra_el_draft() -> None:
    """Dentro de la ventana, deshacer revierte la creación y cierra el draft."""
    tools, repo, drafts, reloj = _escenario()
    draft_id = _crear_cita_auto(tools)
    draft = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert draft is not None
    revertida = undo_draft(
        tenant_id=TENANT, draft_id=draft_id, repo=repo, drafts=drafts, clock=reloj
    )
    assert revertida.status == "cancelled"
    guardada = repo.find_by_correlation_id(tenant_id=TENANT, correlation_id="corr-auto")
    assert guardada is not None and guardada.status == "cancelled"
    tras_undo = drafts.get(tenant_id=TENANT, draft_id=draft_id)
    assert tras_undo is not None and tras_undo.status is DraftStatus.CANCELLED


def test_deshacer_fuera_de_la_ventana_no_se_puede() -> None:
    """Pasados los 30 minutos el commit ya no admite deshacer."""
    tools, repo, drafts, reloj = _escenario()
    draft_id = _crear_cita_auto(tools)
    reloj.avanzar(31)
    with pytest.raises(DraftNotCommittable):
        undo_draft(tenant_id=TENANT, draft_id=draft_id, repo=repo, drafts=drafts, clock=reloj)


def test_deshacer_una_cancelacion_restaura_la_cita() -> None:
    """Deshacer el draft de cancelación devuelve la cita a `confirmed`."""
    tools, repo, drafts, reloj = _escenario()
    creada = tools.propose_appointment(
        tenant_id=TENANT,
        correlation_id="corr-cita",
        conversation_id=CONVERSACION,
        message="cita 2026-03-02 10:00 Ana Pérez 3001112233",
        date="2026-03-02",
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )
    assert creada.appointment is not None
    cancelada = tools.cancel_appointment(
        tenant_id=TENANT,
        correlation_id="corr-cancel",
        conversation_id=CONVERSACION,
        message=f"cancela {creada.appointment.id}",
        appointment_id=creada.appointment.id,
    )
    assert cancelada.draft_id is not None
    revertida = undo_draft(
        tenant_id=TENANT,
        draft_id=cancelada.draft_id,
        repo=repo,
        drafts=drafts,
        clock=reloj,
    )
    assert revertida.status == "confirmed"
