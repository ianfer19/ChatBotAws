"""Nodo `call_tool`: ejecuta la tool elegida sobre los puertos inyectados.

Traduce cualquier `AppError` de las tools a `tool_error` en el estado: el turno no se
rompe por un fallo de negocio (cita inexistente, datos incompletos) y `respond` decide
qué le dice al cliente sin exponer detalles internos.
"""

from shared.errors import AppError
from shared.logging import get_logger
from slices.appointments.application.deps import Deps
from slices.appointments.application.schemas import ToolName, ToolResult
from slices.appointments.application.state import AgentState

_logger = get_logger(__name__)


def _ejecutar(tool_name: ToolName, state: AgentState, deps: Deps) -> ToolResult:
    """Despacha la tool elegida con los argumentos del `proposal` y el contexto del turno.

    Args:
        tool_name: Tool a ejecutar (ya validada contra la allowlist).
        state: Estado con `proposal`, `tenant_id` y `correlation_id`.
        deps: Tools inyectadas (repositorio, reloj y horario).

    Returns:
        La salida de la tool, que pasa a `tool_result`.

    Raises:
        AppError: Cualquier error tipado de la tool (comercio, datos o tenant).
    """
    proposal = state["proposal"]
    tenant_id = state["tenant_id"]
    match tool_name:
        case "get_availability":
            return deps.tools.get_availability(
                tenant_id=tenant_id,
                date=proposal.date or "",
                party_size=proposal.party_size,
            )
        case "propose_appointment":
            return deps.tools.propose_appointment(
                tenant_id=tenant_id,
                correlation_id=state["correlation_id"],
                conversation_id=state["conversation_id"],
                message=state["user_message"],
                date=proposal.date or "",
                time=proposal.time or "",
                customer_name=proposal.customer_name or "",
                contact=proposal.contact or "",
            )
        case "cancel_appointment":
            return deps.tools.cancel_appointment(
                tenant_id=tenant_id,
                correlation_id=state["correlation_id"],
                conversation_id=state["conversation_id"],
                message=state["user_message"],
                appointment_id=proposal.appointment_id or "",
            )
        case "get_opening_hours":
            return deps.tools.get_opening_hours(tenant_id=tenant_id)


def call_tool(state: AgentState, *, deps: Deps) -> AgentState:
    """Ejecuta la tool del turno y guarda `tool_result` o `tool_error` en el estado.

    Args:
        state: Estado con `tool_name`, `proposal` y contexto del turno.
        deps: Tools inyectadas.

    Returns:
        Estado con `tool_result` si todo fue bien, o con `tool_error` (código y
        mensaje de log) si la tool lanzó un `AppError`.

    Raises:
        (ninguna): los errores tipados se traducen a `tool_error`; un `tool_name`
            ausente (imposible en el grafo) también se reporta como error de tool.
    """
    tool_name = state.get("tool_name")
    if tool_name is None:
        return {
            **state,
            "tool_error": {"code": "tool_not_allowed", "message": "sin tool que ejecutar"},
        }
    try:
        result = _ejecutar(tool_name, state, deps)
    except AppError as exc:
        _logger.error("tool de citas falló", extra={"tool": tool_name, "code": exc.code})
        return {**state, "tool_error": {"code": exc.code, "message": str(exc)}}
    _logger.info(
        "tool de citas ejecutada",
        extra={
            "tool": tool_name,
            "draft_id": result.draft_id,
            "draft_status": result.draft_status,
            "policy": result.policy,
            "policy_reasons": list(result.policy_reasons),
        },
    )
    return {**state, "tool_result": result}
