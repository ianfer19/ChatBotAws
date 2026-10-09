"""Nodo `select_action`: elige la tool de la allowlist del slice (regla 1, defensa 1).

La allowlist es el primer anillo de la defensa en profundidad: aunque el modelo proponga
una acción que existe en el Literal pero no está permitida aquí, no se traduce en
`tool_name` y el turno termina en `respond` sin ejecutar nada.
"""

from typing import Literal

from slices.appointments.application.state import AgentState

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "get_availability",
        "propose_appointment",
        "cancel_appointment",
        "get_opening_hours",
    }
)
"""Tools que este grafo sabe ejecutar; debe coincidir con `ToolName` (lo verifican tests)."""


def select_action(state: AgentState) -> AgentState:
    """Fija `tool_name` solo si la acción propuesta es una tool permitida y completa.

    Args:
        state: Estado con `proposal` y `missing_fields`.

    Returns:
        Estado con `tool_name` cuando corresponde; sin cambios de tool cuando la
        propuesta es `reply`, hay datos faltantes o la acción no está en la allowlist.
    """
    proposal = state["proposal"]
    action = proposal.action
    if state.get("missing_fields") or action == "reply" or action not in ALLOWED_TOOLS:
        return {**state}
    return {**state, "tool_name": action}


def ruta_tras_accion(state: AgentState) -> Literal["call_tool", "respond"]:
    """Ruta condicional tras `select_action`: ejecutar la tool o responder directo.

    Args:
        state: Estado con `tool_name` (o sin él).

    Returns:
        `"call_tool"` si hay tool elegida; `"respond"` si no hay nada que ejecutar
        (saludo, aclaración o acción fuera de la allowlist).
    """
    return "call_tool" if state.get("tool_name") else "respond"
