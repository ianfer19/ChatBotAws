"""Nodo `call_tool`: ejecuta la tool elegida sobre los puertos inyectados.

Traduce cualquier `AppError` de las tools a `tool_error` en el estado: el turno no se
rompe por un fallo de negocio (pedido inexistente, fuera de horario) y `respond` decide
qué le dice al cliente sin exponer detalles internos.
"""

from shared.errors import AppError
from shared.logging import get_logger
from slices.orders.application.deps import Deps
from slices.orders.application.schemas import ToolName, ToolResult
from slices.orders.application.state import AgentState

_logger = get_logger(__name__)


def _ejecutar(tool_name: ToolName, state: AgentState, deps: Deps) -> ToolResult:
    """Despacha la tool elegida con los argumentos del `proposal` y el contexto del turno.

    Args:
        tool_name: Tool a ejecutar (ya validada contra la allowlist).
        state: Estado con `proposal`, `tenant_id` y `correlation_id`.
        deps: Tools inyectadas (legacy, catálogo, drafts y horario).

    Returns:
        La salida de la tool, que pasa a `tool_result`.

    Raises:
        AppError: Cualquier error tipado de la tool (catálogo, horario o tenant).
    """
    proposal = state["proposal"]
    tenant_id = state["tenant_id"]
    match tool_name:
        case "search_products":
            return deps.tools.search_products(tenant_id=tenant_id, query=proposal.query or "")
        case "get_menu":
            return deps.tools.get_menu(tenant_id=tenant_id, category=proposal.category)
        case "get_order_status":
            return deps.tools.get_order_status(
                tenant_id=tenant_id, order_id=proposal.order_id or ""
            )
        case "propose_order":
            return deps.tools.propose_order(
                tenant_id=tenant_id,
                correlation_id=state["correlation_id"],
                conversation_id=state["conversation_id"],
                message=state["user_message"],
                items=proposal.items,
            )


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
        _logger.error("tool de pedidos falló", extra={"tool": tool_name, "code": exc.code})
        return {**state, "tool_error": {"code": exc.code, "message": str(exc)}}
    _logger.info(
        "tool de pedidos ejecutada",
        extra={
            "tool": tool_name,
            "draft_id": result.draft_id,
            "draft_status": result.draft_status,
            "policy": result.policy,
            "policy_reasons": list(result.policy_reasons),
        },
    )
    return {**state, "tool_result": result}
