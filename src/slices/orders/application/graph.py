"""Grafo de pedidos de LangGraph: nodos, aristas y compilación (ROADMAP Paso 5).

Orden (espejo del grafo de citas): `understand` → `validate` → `need_more?` →
`select_action` → `call_tool` → `validate_result` → `needs_confirmation?` → `respond` →
`END`. No hay checkpointer todavía: la persistencia entre turnos llega con el Paso 8
(`TODO(decision)`).

Los nodos reciben sus dependencias por `partial` (DI manual): quien construye el grafo
decide si el LLM es Bedrock o un doble de test, y si el legacy es memoria o HTTP tras
AgentCore Gateway (Paso 11).
"""

from collections.abc import Sequence
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from shared.ports import ClockPort, DraftStorePort, LLMPort
from slices.orders.application.deps import Deps
from slices.orders.application.nodes import (
    call_tool,
    need_more,
    respond,
    ruta_confirmacion,
    ruta_tras_accion,
    select_action,
    understand,
    validate,
    validate_result,
)
from slices.orders.application.schemas import KitchenHoursDay, ToolName
from slices.orders.application.state import AgentState
from slices.orders.application.tools import OrderTools
from slices.orders.domain.policy import MONTO_UMBRAL
from slices.orders.domain.ports import CatalogPort, LegacyOrdersPort
from slices.orders.domain.rules import MINIMO_COMPRA


# Nota pyrefly: `AgentState` (TypedDict) no pasa el bound `StateLike` de langgraph:
# pyrefly ve `TypedDict.__required_keys__` sin `ClassVar` (falla el protocolo V1) y
# rechaza atributos de cuerpo de clase sin `ClassVar` en objetos-clase (falla el V2).
# mypy y el runtime de langgraph sí aceptan este grafo (lo ejecutan los tests), así que
# los dos `ignore` de este fichero son solo para pyrefly.
def build_order_graph(
    *,
    llm: LLMPort,
    legacy: LegacyOrdersPort,
    catalog: CatalogPort,
    clock: ClockPort,
    kitchen_hours: Sequence[KitchenHoursDay],
    drafts: DraftStorePort,
    minimum: float = MINIMO_COMPRA,
    amount_threshold: float = MONTO_UMBRAL,
    allowed_tools: frozenset[ToolName] | None = None,
) -> CompiledStateGraph[AgentState, Any, Any, Any]:  # pyrefly: ignore[bad-specialization]
    """Construye y compila el grafo de pedidos con las dependencias del entorno.

    Args:
        llm: Modelo de lenguaje (`BedrockLLM` en producción, doble guionizado en tests).
        legacy: Backend de pedidos (doble en memoria hasta el Paso 11).
        catalog: Catálogo de productos del comercio.
        clock: Reloj inyectable (horario de cocina y ventana de deshacer).
        kitchen_hours: Horario de cocina del comercio (falso hasta RAG/Paso 7).
        drafts: Store de propuestas pendientes (ADR 0011; `InMemoryDraftStore` en
            desarrollo, DynamoDB `pending_actions` en el Paso 6).
        minimum: Mínimo de compra del comercio (pesos).
        amount_threshold: Monto desde el cual el pedido exige confirmación.
        allowed_tools: Entitlements finos del comercio (Fase 4 del Paso 5); `None`
            permite toda la allowlist del slice.

    Returns:
        Grafo compilado, listo para `invoke` con un estado inicial `AgentState`.

    Raises:
        AppError: Si el prompt base de pedidos no se puede cargar (fichero ausente).
    """
    deps = Deps(
        llm=llm,
        tools=OrderTools(
            legacy=legacy,
            catalog=catalog,
            drafts=drafts,
            clock=clock,
            kitchen_hours=kitchen_hours,
            minimum=minimum,
            amount_threshold=amount_threshold,
        ),
        clock=clock,
        allowed_tools=allowed_tools,
    )
    graph = StateGraph(AgentState)  # pyrefly: ignore[bad-specialization]
    graph.add_node("understand", partial(understand, deps=deps))
    graph.add_node("validate", validate)
    graph.add_node("select_action", partial(select_action, deps=deps))
    graph.add_node("call_tool", partial(call_tool, deps=deps))
    graph.add_node("validate_result", validate_result)
    graph.add_node("respond", partial(respond, deps=deps))

    graph.add_edge(START, "understand")
    graph.add_edge("understand", "validate")
    graph.add_conditional_edges(
        "validate",
        need_more,
        {"select_action": "select_action", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "select_action",
        ruta_tras_accion,
        {"call_tool": "call_tool", "respond": "respond"},
    )
    graph.add_edge("call_tool", "validate_result")
    graph.add_conditional_edges(
        "validate_result",
        ruta_confirmacion,
        {"confirmar": "respond", "entregar": "respond"},
    )
    graph.add_edge("respond", END)
    return graph.compile()
