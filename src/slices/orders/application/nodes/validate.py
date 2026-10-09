"""Nodo `validate`: calcula qué datos faltan y enruta según eso (`need_more`).

La decisión de «¿se puede actuar o hay que pedir datos?» es de dominio (`validate_cart`
y la presencia de query/order_id), no del modelo: el LLM solo propone, este nodo juzga.
El carrito vacío nunca llega a una tool de escritura (regla 5).
"""

from typing import Literal

from slices.orders.application.state import AgentState


def validate(state: AgentState) -> AgentState:
    """Completa `missing_fields` según la acción propuesta por `understand`.

    Args:
        state: Estado con `proposal` ya validado.

    Returns:
        Estado con `missing_fields`: lista vacía si la petición está completa para la
        acción elegida (`reply` y `get_menu` nunca tienen campos pendientes).
    """
    proposal = state["proposal"]
    faltantes: list[str]
    if proposal.action == "propose_order":
        faltantes = ["items"] if not proposal.items else []
    elif proposal.action == "search_products":
        faltantes = ["query"] if not proposal.query else []
    elif proposal.action == "get_order_status":
        faltantes = ["order_id"] if not proposal.order_id else []
    else:
        faltantes = []
    return {**state, "missing_fields": faltantes}


def need_more(state: AgentState) -> Literal["select_action", "respond"]:
    """Ruta condicional tras `validate`: ¿hay datos para actuar o hay que pedirlos?

    Args:
        state: Estado con `missing_fields` calculado por `validate`.

    Returns:
        `"select_action"` si la petición está completa; `"respond"` para pedir los
        datos que faltan (regla 5: nada se propone sin carrito).
    """
    return "respond" if state.get("missing_fields") else "select_action"
