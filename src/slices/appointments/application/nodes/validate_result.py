"""Nodo `validate_result`: coherencia de la salida y si hace falta confirmación.

Comprueba que lo que devolvió la tool corresponde a la tool pedida (defensa contra
estados corruptos o nodos mal cableados) y marca `needs_confirmation` cuando el draft
sigue `AWAITING_CONFIRMATION`: la confirmación sale de la política de riesgo (ADR
0011), no de una lista fija de acciones.
"""

from typing import Literal

from shared.contracts.pending import DraftStatus
from shared.errors import ToolError
from slices.appointments.application.state import AgentState


def validate_result(state: AgentState) -> AgentState:
    """Valida `tool_result` frente a `tool_name` y fija `needs_confirmation`.

    Args:
        state: Estado tras `call_tool`.

    Returns:
        Estado con `needs_confirmation`: `False` si hubo error, `True` si el draft de
        la propuesta espera confirmación del cliente y `False` en cualquier otro caso
        (consulta o escritura ya commiteada).

    Raises:
        ToolError: Si no hay resultado o no corresponde a la tool pedida (estado
            inconsistente: no se puede redactar una respuesta a ciegas).
    """
    tool_name = state.get("tool_name")
    if state.get("tool_error"):
        return {**state, "needs_confirmation": False}
    result = state.get("tool_result")
    if result is None or tool_name is None or result.tool != tool_name:
        raise ToolError(
            "resultado de tool incoherente con la pedida",
            details={"esperada": tool_name or "ninguna"},
        )
    return {
        **state,
        "needs_confirmation": result.draft_status is DraftStatus.AWAITING_CONFIRMATION,
    }


def ruta_confirmacion(state: AgentState) -> Literal["confirmar", "entregar"]:
    """Ruta condicional tras `validate_result` (hoy ambas terminan en `respond`).

    Args:
        state: Estado con `needs_confirmation` calculado.

    Returns:
        `"confirmar"` si el resultado pide confirmación; `"entregar"` en caso
        contrario. Queda como punto de enganche para el HITL real (Paso 8,
        `TODO(decision)`): hoy el turno solo pide confirmación con la respuesta.
    """
    return "confirmar" if state.get("needs_confirmation") else "entregar"
