"""Nodo `decide`: aplica las reglas del dominio y traduce sus errores a respuesta.

El único sitio donde se decide el destino (`resolve_route`): ambigüedad y bots no
habilitados no interrumpen el turno, sino que se convierten en una respuesta honesta
del supervisor con su `route_error` para logs y métricas. El saludo llega aquí como
cualquier otra intención y sale hacia `greet`.
"""

from shared.logging import get_logger
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.errors import AmbiguousIntentError, IntentNotAllowedByTenant
from slices.supervisor.domain.routing import resolve_route

_logger = get_logger(__name__)

_MSG_NO_ENTENDI = "No estoy seguro de entender tu mensaje. ¿Puedes escribirlo de otra forma?"
_MSG_NO_DISPONIBLE = (
    "Ese servicio aún no está disponible en este comercio. ¿Puedo ayudarte con otra cosa?"
)


def decide(state: SupervisorState, *, deps: Deps) -> SupervisorState:
    """Resuelve el agente destino o, si la decisión no es segura, su respuesta directa.

    Args:
        state: Turno clasificado (`intent`, `confidence`).
        deps: Entitlements del comercio (`allowed_bots`).

    Returns:
        Estado con `target` si la ruta es válida, o con `reply` + `route_error` si el
        dominio la rechazó (ambigüedad o bot no habilitado).
    """
    mensaje = state["message"]
    try:
        destino = resolve_route(
            intent=state["intent"],
            confidence=state["confidence"],
            allowed_bots=deps.allowed_bots,
        )
    except AmbiguousIntentError:
        _logger.info(
            "supervisor.ambiguous_intent",
            extra={"tenant_id": mensaje.tenant_id, "correlation_id": mensaje.correlation_id},
        )
        return {**state, "route_error": "ambiguous_intent", "reply": _MSG_NO_ENTENDI}
    except IntentNotAllowedByTenant:
        _logger.info(
            "supervisor.intent_not_allowed",
            extra={"tenant_id": mensaje.tenant_id, "correlation_id": mensaje.correlation_id},
        )
        return {**state, "route_error": "intent_not_allowed", "reply": _MSG_NO_DISPONIBLE}
    return {**state, "target": destino}
