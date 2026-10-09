"""Nodo `select_action`: elige la tool de la allowlist del slice (capa 1, defensa 1).

La allowlist es el primer anillo de la defensa en profundidad: aunque el modelo proponga
una acción que exista en su imaginación (p. ej. «cambiar la hora del pedido»), no está
aquí, no se traduce en `tool_name` y el turno termina en `respond` sin ejecutar nada.
No existe ni existirá una tool de hora en este slice (AGENTS raíz §7). Además, la
composición puede recortar la allowlist por comercio con `Deps.allowed_tools`
(principio de mínimo privilegio, Fase 4 del Paso 5).
"""

from typing import Literal

from slices.orders.application.deps import Deps
from slices.orders.application.state import AgentState

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "search_products",
        "get_menu",
        "get_order_status",
        "propose_order",
    }
)
"""Tools que este grafo sabe ejecutar; debe coincidir con `ToolName` (lo verifican tests)."""


def select_action(state: AgentState, *, deps: Deps | None = None) -> AgentState:
    """Fija `tool_name` solo si la acción propuesta es una tool permitida y completa.

    Args:
        state: Estado con `proposal` y `missing_fields`.
        deps: Dependencias con los entitlements `allowed_tools` del comercio; `None`
            (llamada directa de test) usa la allowlist completa del slice.

    Returns:
        Estado con `tool_name` cuando corresponde; sin cambios de tool cuando la
        propuesta es `reply`, hay datos faltantes o la acción no está en la
        intersección `ALLOWED_TOOLS ∩ allowed_tools`.
    """
    proposal = state["proposal"]
    action = proposal.action
    permitidas = ALLOWED_TOOLS
    if deps is not None and deps.allowed_tools is not None:
        permitidas = ALLOWED_TOOLS & deps.allowed_tools
    if state.get("missing_fields") or action == "reply" or action not in permitidas:
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
