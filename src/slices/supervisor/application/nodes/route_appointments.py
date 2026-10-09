"""Nodo `route_appointments`: invoca el grafo de citas (nodo anidado, ADR 0010).

Compone el estado que el especialista espera (`tenant_id`, `correlation_id`,
`user_message`, `history`), ejecuta su turno completo y refleja la respuesta final en
el estado del supervisor junto al contrato `RoutedTurn` de salida. Si el especialista
no devuelve respuesta (no debería pasar: su grafo siempre redacta), se degrada a un
mensaje honesto en lugar de entregar un turno vacío al canal.
"""

from shared.contracts import RoutedTurn
from shared.logging import get_logger
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.state import SupervisorState

_logger = get_logger(__name__)

_MSG_SIN_RESPUESTA = "No pude preparar la respuesta. ¿Puedes repetir tu mensaje?"


def route_appointments(state: SupervisorState, *, deps: Deps) -> SupervisorState:
    """Ejecuta el turno en el grafo de citas y devuelve su respuesta como salida propia.

    Args:
        state: Turno decidido hacia `appointments` (con `history` y `context` ya
            garantizados por `load_context`).
        deps: Grafo de citas compilado e inyectado.

    Returns:
        Estado con `reply` (respuesta del especialista) y `routed` (contrato de salida).

    Raises:
        AppError: Los errores del especialista (LLM caído, tools rotas) se propagan sin
            traducir aquí: los gestiona quien despache el turno (handler, Paso 9).
    """
    mensaje = state["message"]
    entrada = {
        "tenant_id": mensaje.tenant_id,
        "correlation_id": mensaje.correlation_id,
        "user_message": mensaje.text or "",
        "history": list(state["history"]),
    }
    resultado = deps.appointments_graph.invoke(entrada)
    reply = resultado.get("reply") if isinstance(resultado, dict) else None
    if not isinstance(reply, str) or not reply:
        _logger.warning(
            "supervisor.empty_specialist_reply",
            extra={"tenant_id": mensaje.tenant_id, "correlation_id": mensaje.correlation_id},
        )
        reply = _MSG_SIN_RESPUESTA
    routed = RoutedTurn(message=mensaje, intent=state["intent"], target="appointments")
    _logger.info(
        "supervisor.routed",
        extra={
            "tenant_id": mensaje.tenant_id,
            "correlation_id": mensaje.correlation_id,
            "target": "appointments",
        },
    )
    return {**state, "reply": reply, "routed": routed}
