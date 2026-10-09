"""Nodo `load_context`: primer paso obligatorio de todo turno (requisito 7.2).

Garantiza que el clasificador nunca vea un turno «a medias»: exige la ventana de
historial que debe enviar el llamador y lee el contexto de cliente con los ids del
mensaje (inyectados desde el estado, nunca pedidos al modelo). Si algo falta, el turno
falla aquí mismo en lugar de construir un prompt incompleto.
"""

from slices.supervisor.application.deps import Deps
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.errors import MissingTurnInputsError


def load_context(state: SupervisorState, *, deps: Deps) -> SupervisorState:
    """Lee el contexto del cliente y exige el historial antes de clasificar.

    Args:
        state: Turno entrante; usa `message` y (obligatorio) `history`.
        deps: Lector de contexto inyectado por el constructor del grafo.

    Returns:
        Estado con `context` siempre presente.

    Raises:
        MissingTurnInputsError: Si falta la ventana de historial, si el mensaje viene
            sin texto o si el lector devuelve `None` (turno sin contexto).
    """
    mensaje = state["message"]
    if "history" not in state:
        raise MissingTurnInputsError(
            "el turno llegó sin ventana de historial",
            details={"correlation_id": mensaje.correlation_id},
        )
    if mensaje.text is None or not mensaje.text.strip():
        raise MissingTurnInputsError(
            "el turno llegó sin texto",
            details={"correlation_id": mensaje.correlation_id},
        )
    contexto = deps.context_reader.get_customer_context(
        tenant_id=mensaje.tenant_id, customer_id=mensaje.customer_id
    )
    if contexto is None:
        raise MissingTurnInputsError(
            "el turno llegó sin contexto de cliente",
            details={"correlation_id": mensaje.correlation_id},
        )
    return {**state, "context": contexto}
