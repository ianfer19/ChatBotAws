"""Tests de las reglas de dominio de citas: datos mínimos, solapes y horario."""

from datetime import datetime

from slices.appointments.domain.entities import Appointment, AppointmentStatus
from slices.appointments.domain.hours import OpeningHoursDay
from slices.appointments.domain.rules import (
    CAMPOS_OBLIGATORIOS,
    DURACION_CITA,
    missing_appointment_fields,
    overlapping_appointment,
    within_opening_hours,
)

LUNES = OpeningHoursDay(weekday=0, open_time="09:00", close_time="12:00")


def _cita(
    start: datetime,
    *,
    appointment_id: str = "c-1",
    status: AppointmentStatus = "confirmed",
) -> Appointment:
    """Construye una cita sintética para las reglas de solape.

    Args:
        start: Inicio de la cita.
        appointment_id: Identificador de la cita.
        status: Estado de la cita (`confirmed` ocupa turno, `cancelled` no).

    Returns:
        La cita ya validada.
    """
    return Appointment(
        id=appointment_id,
        tenant_id="Sede_Elite_01",
        starts_at=start,
        customer_name="Ana Pérez",
        contact="3001112233",
        status=status,
    )


def test_propuesta_completa_no_tiene_campos_faltantes() -> None:
    """Con los cuatro datos presentes no hay nada que pedir al cliente."""
    faltantes = missing_appointment_fields(
        date="2026-03-05",
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )
    assert faltantes == []


def test_faltantes_devueltos_en_el_orden_de_la_regla() -> None:
    """Los campos ausentes salen en el orden canónico para pedirlos de una sola vez."""
    faltantes = missing_appointment_fields(
        date="2026-03-05",
        time=None,
        customer_name="",
        contact=None,
    )
    assert faltantes == ["time", "customer_name", "contact"]
    assert list(CAMPOS_OBLIGATORIOS) == ["date", "time", "customer_name", "contact"]


def test_solape_en_el_mismo_inicio_detecta_la_cita() -> None:
    """Dos citas en el mismo turno no pueden coexistir (regla 2)."""
    existente = _cita(datetime(2026, 3, 2, 10, 0))
    choque = overlapping_appointment(start=datetime(2026, 3, 2, 10, 0), existing=[existente])
    assert choque is existente


def test_solape_parcial_detecta_la_cita() -> None:
    """Un inicio dentro de la duración de otra cita también solapa."""
    existente = _cita(datetime(2026, 3, 2, 10, 0))
    choque = overlapping_appointment(start=datetime(2026, 3, 2, 10, 30), existing=[existente])
    assert choque is existente


def test_turno_adyacente_no_solapa() -> None:
    """La siguiente cita empieza justo cuando termina la anterior: sin choque."""
    existente = _cita(datetime(2026, 3, 2, 10, 0))
    choque = overlapping_appointment(start=datetime(2026, 3, 2, 11, 0), existing=[existente])
    assert choque is None
    assert DURACION_CITA.total_seconds() == 3600


def test_una_cita_cancelada_no_ocupa_turno() -> None:
    """Cancelar libera el hueco: las canceladas no cuentan para el solape."""
    cancelada = _cita(datetime(2026, 3, 2, 10, 0), status="cancelled")
    choque = overlapping_appointment(start=datetime(2026, 3, 2, 10, 0), existing=[cancelada])
    assert choque is None


def test_dentro_del_horario_es_valido() -> None:
    """Un turno que cabe entero en la franja del día está dentro (regla 3)."""
    assert within_opening_hours(start=datetime(2026, 3, 2, 10, 0), opening_hours=[LUNES])


def test_antes_de_la_apertura_no_esta_dentro() -> None:
    """Empezar antes de abrir (aunque termine dentro) no es horario válido."""
    assert not within_opening_hours(start=datetime(2026, 3, 2, 8, 0), opening_hours=[LUNES])


def test_que_sale_del_cierre_no_esta_dentro() -> None:
    """La cita de 11:00 termina a las 12:00 y la de 11:30 se pasa: fuera de franja."""
    assert within_opening_hours(start=datetime(2026, 3, 2, 11, 0), opening_hours=[LUNES])
    assert not within_opening_hours(start=datetime(2026, 3, 2, 11, 30), opening_hours=[LUNES])


def test_dia_sin_franja_o_sin_horario_nunca_esta_dentro() -> None:
    """Un martes sin franjas (o un comercio sin horario) no admite turnos."""
    assert not within_opening_hours(start=datetime(2026, 3, 3, 10, 0), opening_hours=[LUNES])
    assert not within_opening_hours(start=datetime(2026, 3, 2, 10, 0), opening_hours=[])
