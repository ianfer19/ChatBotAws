"""Tests del repositorio de citas en memoria (doble del Paso 1) y de su entidad."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from shared.errors import ValidationError
from slices.appointments.domain.entities import Appointment
from slices.appointments.domain.ports import AppointmentRepositoryPort
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Otro_Comercio_01"


def _cita(
    appointment_id: str = "c-1",
    *,
    tenant_id: str = TENANT,
    start: datetime = datetime(2026, 10, 10, 10, 0, tzinfo=UTC),
    correlation_id: str | None = "corr-1",
) -> Appointment:
    """Construye una cita sintética de prueba (sin lógica de negocio).

    Args:
        appointment_id: Identificador de la cita.
        tenant_id: Comercio dueño de la cita.
        start: Inicio de la cita.
        correlation_id: Clave de idempotencia de la creación.

    Returns:
        Cita ya validada por el modelo.
    """
    return Appointment(
        id=appointment_id,
        tenant_id=tenant_id,
        starts_at=start,
        customer_name="Ana Pérez",
        contact="3001112233",
        status="confirmed",
        correlation_id=correlation_id,
    )


def test_doble_cumple_el_puerto_del_dominio() -> None:
    """mypy y `isinstance` confirman que el doble implementa `AppointmentRepositoryPort`."""
    repo: AppointmentRepositoryPort = InMemoryAppointmentRepository()
    assert isinstance(repo, AppointmentRepositoryPort)


def test_guardar_y_buscar_una_cita() -> None:
    """El ciclo básico del repositorio devuelve exactamente lo guardado."""
    repo = InMemoryAppointmentRepository()
    cita = _cita()
    repo.save(tenant_id=TENANT, appointment=cita)
    assert repo.find(tenant_id=TENANT, appointment_id="c-1") == cita


def test_una_cita_de_otro_comercio_es_inexistente() -> None:
    """Nunca se informa que una cita existe "en otro comercio": simplemente no se ve."""
    repo = InMemoryAppointmentRepository()
    repo.save(tenant_id=TENANT, appointment=_cita())
    assert repo.find(tenant_id=OTRO_TENANT, appointment_id="c-1") is None


def test_no_se_puede_guardar_una_cita_ajena_al_tenant() -> None:
    """El tenant de la entidad y el del contexto deben coincidir (defensa en profundidad)."""
    repo = InMemoryAppointmentRepository()
    with pytest.raises(ValidationError):
        repo.save(tenant_id=OTRO_TENANT, appointment=_cita(tenant_id=TENANT))


def test_sin_tenant_no_se_ejecuta_ninguna_operacion() -> None:
    """Un `tenant_id` vacío es un bug de composición y se rechaza de inmediato."""
    repo = InMemoryAppointmentRepository()
    with pytest.raises(ValidationError):
        repo.find(tenant_id="", appointment_id="c-1")
    with pytest.raises(ValidationError):
        repo.save(tenant_id="", appointment=_cita())


def test_idempotencia_por_correlation_id() -> None:
    """Reintentar la misma creación devuelve la cita ya guardada, sin duplicar."""
    repo = InMemoryAppointmentRepository()
    repo.save(tenant_id=TENANT, appointment=_cita(correlation_id="corr-7"))
    encontrada = repo.find_by_correlation_id(tenant_id=TENANT, correlation_id="corr-7")
    assert encontrada is not None and encontrada.id == "c-1"
    assert repo.find_by_correlation_id(tenant_id=OTRO_TENANT, correlation_id="corr-7") is None


def test_listado_por_periodo_ordenado_y_acotado_al_tenant() -> None:
    """Solo las citas del tenant dentro del periodo, ordenadas por inicio."""
    repo = InMemoryAppointmentRepository()
    repo.save(
        tenant_id=TENANT, appointment=_cita("c-2", start=datetime(2026, 10, 12, 9, 0, tzinfo=UTC))
    )
    repo.save(
        tenant_id=TENANT, appointment=_cita("c-1", start=datetime(2026, 10, 10, 10, 0, tzinfo=UTC))
    )
    repo.save(
        tenant_id=OTRO_TENANT,
        appointment=_cita(
            "c-9", tenant_id=OTRO_TENANT, start=datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
        ),
    )
    citas = repo.list_for_period(
        tenant_id=TENANT,
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 31, tzinfo=UTC),
    )
    assert [cita.id for cita in citas] == ["c-1", "c-2"]


def test_periodo_invertido_es_error_de_validacion() -> None:
    """Un rango imposible es un error del llamador, no un listado vacío silencioso."""
    repo = InMemoryAppointmentRepository()
    with pytest.raises(ValidationError):
        repo.list_for_period(
            tenant_id=TENANT,
            start=datetime(2026, 10, 31, tzinfo=UTC),
            end=datetime(2026, 10, 1, tzinfo=UTC),
        )


def test_entidad_inmutable_y_sin_campos_ajenos() -> None:
    """La cita ya guardada no admite cambios laterales ni campos no previstos."""
    cita = _cita()
    with pytest.raises(PydanticValidationError):
        cita.status = "cancelled"  # pyrefly: ignore[read-only]
    with pytest.raises(PydanticValidationError):
        Appointment.model_validate({**cita.model_dump(), "price": 10_000})
