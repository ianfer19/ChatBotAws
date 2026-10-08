"""Tests de la regla de dominio «datos mínimos para crear una cita» (regla 4)."""

from slices.appointments.domain.rules import CAMPOS_OBLIGATORIOS, missing_appointment_fields


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
