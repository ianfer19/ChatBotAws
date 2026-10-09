"""Nodo `validate`: calcula qué datos faltan (regla 4) y enruta según eso (`need_more`).

La decisión de «¿se puede actuar o hay que pedir datos?» es de dominio
(`missing_appointment_fields`), no del modelo: el LLM solo propone, este nodo juzga.
"""

from typing import Literal

from slices.appointments.application.state import AgentState
from slices.appointments.domain.rules import missing_appointment_fields


def validate(state: AgentState) -> AgentState:
    """Completa `missing_fields` según la acción propuesta por `understand`.

    Args:
        state: Estado con `proposal` ya validado.

    Returns:
        Estado con `missing_fields`: lista vacía si la petición está completa para la
        acción elegida (`reply` nunca tiene campos pendientes).
    """
    proposal = state["proposal"]
    faltantes: list[str]
    if proposal.action == "propose_appointment":
        faltantes = missing_appointment_fields(
            date=proposal.date,
            time=proposal.time,
            customer_name=proposal.customer_name,
            contact=proposal.contact,
        )
    elif proposal.action == "get_availability":
        faltantes = ["date"] if not proposal.date else []
    elif proposal.action == "cancel_appointment":
        faltantes = ["appointment_id"] if not proposal.appointment_id else []
    else:
        faltantes = []
    return {**state, "missing_fields": faltantes}


def need_more(state: AgentState) -> Literal["select_action", "respond"]:
    """Ruta condicional tras `validate`: ¿hay datos para actuar o hay que pedirlos?

    Args:
        state: Estado con `missing_fields` calculado por `validate`.

    Returns:
        `"select_action"` si la petición está completa; `"respond"` para pedir los
        datos que faltan (regla 4: nada se crea sin ellos).
    """
    return "respond" if state.get("missing_fields") else "select_action"
