"""Nodo `route_orders`: invoca el grafo de pedidos (nodo anidado, ADR 0010).

Espejo de `route_appointments`: compone el estado que el especialista espera
(`tenant_id`, `correlation_id`, `conversation_id`, `user_message`, `history`), ejecuta
su turno completo y refleja la respuesta final en el estado del supervisor junto al
contrato `RoutedTurn` de salida. Si el grafo no está inyectado o no devuelve respuesta
(no debería pasar: su grafo siempre redacta), se degrada a un mensaje honesto en lugar
de entregar un turno vacío al canal.
"""

from shared.contracts import RoutedTurn
from shared.logging import get_logger
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.state import SupervisorState

_logger = get_logger(__name__)

_MSG_SIN_RESPUESTA = "No pude preparar la respuesta. ¿Puedes repetir tu mensaje?"


def route_orders(state: SupervisorState, *, deps: Deps) -> SupervisorState:
    """Ejecuta el turno en el grafo de pedidos y devuelve su respuesta como salida propia.

    Args:
        state: Turno decidido hacia `orders` (con `history` y `context` ya garantizados
            por `load_context`).
        deps: Grafo de pedidos compilado e inyectado (opcional hasta Fase 3).

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
        # Compuesto hasta que el gateway aporte la conversación real (Paso 9,
        # TODO(verify)): estable entre turnos del mismo cliente en el mismo canal,
        # que es lo que exige la ranura de drafts del ADR 0011.
        "conversation_id": f"{mensaje.channel}:{mensaje.customer_id}",
        "user_message": mensaje.text or "",
        "history": list(state["history"]),
    }
    reply: str | None = None
    if deps.orders_graph is not None:
        resultado = deps.orders_graph.invoke(entrada)
        candidato = resultado.get("reply") if isinstance(resultado, dict) else None
        reply = candidato if isinstance(candidato, str) and candidato else None
    if reply is None:
        _logger.warning(
            "supervisor.empty_specialist_reply",
            extra={"tenant_id": mensaje.tenant_id, "correlation_id": mensaje.correlation_id},
        )
        reply = _MSG_SIN_RESPUESTA
    routed = RoutedTurn(message=mensaje, intent=state["intent"], target="orders")
    _logger.info(
        "supervisor.routed",
        extra={
            "tenant_id": mensaje.tenant_id,
            "correlation_id": mensaje.correlation_id,
            "target": "orders",
        },
    )
    return {**state, "reply": reply, "routed": routed}
