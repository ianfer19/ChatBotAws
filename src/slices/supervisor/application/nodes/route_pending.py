"""Nodo `route_pending`: deja el turno enrutado a un especialista aún no construido.

Ventas, pedidos y FAQ se enrutan desde ya con su contrato de salida `RoutedTurn` (el
handler de turno completo los despachará cuando existan esos grafos, Pasos 5+). El
supervisor no redacta aquí: no conoce el negocio de esos agentes.
"""

from shared.contracts import RoutedTurn
from shared.logging import get_logger
from slices.supervisor.application.state import SupervisorState

_logger = get_logger(__name__)


def route_pending(state: SupervisorState) -> SupervisorState:
    """Registra el `RoutedTurn` hacia el agente destino pendiente de construir.

    Args:
        state: Turno decidido hacia `sales`, `orders` o `faq`.

    Returns:
        Estado con `routed` (y sin `reply`: la respuesta la dará el especialista).
    """
    mensaje = state["message"]
    routed = RoutedTurn(message=mensaje, intent=state["intent"], target=state["target"])
    _logger.info(
        "supervisor.routed",
        extra={
            "tenant_id": mensaje.tenant_id,
            "correlation_id": mensaje.correlation_id,
            "target": state["target"],
        },
    )
    return {**state, "routed": routed}
