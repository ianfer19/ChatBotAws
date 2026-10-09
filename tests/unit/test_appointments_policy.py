"""Tests de la política de riesgo de citas: campos inferidos y decisión (ADR 0011)."""

from shared.contracts.pending import ConfirmationPolicy
from slices.appointments.domain.policy import decide_appointment, detect_inferred_fields

_CAMPOS = {
    "date": "2026-03-02",
    "time": "10:00",
    "customer_name": "Ana Pérez",
    "contact": "3001112233",
}


def test_todo_lo_literal_en_el_mensaje_no_infiere_nada() -> None:
    """Con los cuatro valores escritos en el mensaje no hay nada inferido."""
    inferidos = detect_inferred_fields(
        message="cita 2026-03-02 10:00 Ana Pérez 3001112233", fields=_CAMPOS
    )
    assert inferidos == ()


def test_la_fecha_relativa_cuenta_como_dicha() -> None:
    """«El viernes» es una fecha explícita aunque el valor ISO no aparezca."""
    inferidos = detect_inferred_fields(
        message="quiero cita el viernes a las 10:00 de Ana Pérez 3001112233",
        fields={"date": "2026-03-06", "time": "10:00"},
    )
    assert inferidos == ()


def test_la_hora_relativa_cuenta_como_dicha() -> None:
    """«A las 10» es una hora explícita aunque no venga como `10:00`."""
    inferidos = detect_inferred_fields(
        message="cita 2026-03-02 a las 10 con Ana Pérez 3001112233",
        fields={"date": "2026-03-02", "time": "10:00"},
    )
    assert inferidos == ()


def test_la_comparacion_ignora_mayusculas_y_acentos() -> None:
    """«ANA PÉREZ» en el mensaje da por dicho el campo «Ana Pérez»."""
    inferidos = detect_inferred_fields(
        message="cita ANA PÉREZ 3001112233 2026-03-02 10:00", fields=_CAMPOS
    )
    assert inferidos == ()


def test_un_campo_no_dicho_se_marca_inferido() -> None:
    """El contacto que no aparece en el mensaje es inferido por el modelo."""
    inferidos = detect_inferred_fields(message="cita 2026-03-02 10:00 Ana Pérez", fields=_CAMPOS)
    assert inferidos == ("contact",)


def test_los_valores_vacios_no_se_consideran_inferidos() -> None:
    """Sin nada en el mensaje todo se da por inferido; un valor vacío no cuenta."""
    inferidos = detect_inferred_fields(message="", fields={"date": "2026-03-02"})
    assert inferidos == ("date",)
    inferidos_vacio = detect_inferred_fields(message="", fields={"date": ""})
    assert inferidos_vacio == ()


def test_decide_sin_inferidos_es_auto() -> None:
    """Todo dicho por el cliente: se ejecuta solo, con ventana de deshacer."""
    decision = decide_appointment(inferred_fields=())
    assert decision.policy is ConfirmationPolicy.AUTO
    assert decision.reasons == ()


def test_decide_con_inferidos_es_confirm_con_motivos() -> None:
    """Un solo campo inferido ya exige confirmación, con su motivo trazable."""
    decision = decide_appointment(inferred_fields=("contact", "date"))
    assert decision.policy is ConfirmationPolicy.CONFIRM
    assert decision.reasons == ("campo_inferido:contact", "campo_inferido:date")
