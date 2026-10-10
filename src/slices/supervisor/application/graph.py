"""Grafo del supervisor: nodos, aristas y compilación (ROADMAP Paso 4, Fase 4 Paso 5).

Orden: `load_context` → `resolve_pending` → [fin | classify] → decide → [greet |
route_appointments | route_orders | route_faq | route_pending | fin]. El router de
pendientes (ADR 0011.5) resuelve drafts a la espera con respuesta plantilla antes de
clasificar; el saludo y las respuestas degradadas terminan en el propio supervisor;
las citas, los pedidos y el FAQ se ejecutan invocando su grafo ya compilado (nodo
anidado, ADR 0010) y `route_pending` deja el `RoutedTurn` para cuando esos grafos no
estén inyectados (ventas no existe todavía; FAQ y pedidos son opcionales).

Las dependencias llegan por `partial` (DI manual): quien construye el grafo decide si
el LLM es Bedrock o un doble, quién lee el contexto de cliente, con qué entitlements
corre cada comercio y con qué confirmer se resuelven los drafts.
"""

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from shared.contracts import AgentName
from shared.ports import DraftStorePort, LLMPort
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.nodes import (
    classify,
    decide,
    greet,
    load_context,
    resolve_pending,
    route_appointments,
    route_faq,
    route_orders,
    route_pending,
    ruta_tras_decidir,
    ruta_tras_pendiente,
)
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.ports import (
    ConfirmerPort,
    ContextReaderPort,
    SpecialistGraphPort,
)


# Nota pyrefly: mismo caso que `appointments/application/graph.py` — `TypedDict` no pasa
# el bound `StateLike` de langgraph; mypy y el runtime sí (lo ejecutan los tests).
def build_supervisor_graph(
    *,
    llm: LLMPort,
    context_reader: ContextReaderPort,
    allowed_bots: frozenset[AgentName],
    appointments_graph: SpecialistGraphPort,
    orders_graph: SpecialistGraphPort | None = None,
    faq_graph: SpecialistGraphPort | None = None,
    draft_store: DraftStorePort | None = None,
    confirmer: ConfirmerPort | None = None,
) -> CompiledStateGraph[SupervisorState, Any, Any, Any]:  # pyrefly: ignore[bad-specialization]
    """Construye y compila el grafo del supervisor con las dependencias del entorno.

    Args:
        llm: Modelo clasificador (`BedrockLLM` en producción, doble en tests).
        context_reader: Lector del contexto de cliente (tool de `customer_context`).
        allowed_bots: Entitlements del comercio (hoy fijos en la composición;
            `TODO(decision)`: resolverse por tenant en el handler, Paso 9).
        appointments_graph: Grafo de citas compilado que se invoca al enrutar.
        orders_graph: Grafo de pedidos compilado (Fase 3 del Paso 5); `None` deja los
            pedidos en `route_pending` (retrocompatible con composiciones previas).
        faq_graph: Grafo de respuestas de conocimiento compilado (Paso 7); `None`
            deja el FAQ en `route_pending` (retrocompatible con composiciones previas).
        draft_store: Store de drafts para el router `resolve_pending` (Fase 4);
            `None` desactiva el router (los drafts los resuelven las tools).
        confirmer: Resolución de drafts (affirm/deny/undo) de la composición;
            `None` desactiva el router junto a `draft_store`.

    Returns:
        Grafo compilado, listo para `invoke` con un estado inicial `SupervisorState`.

    Raises:
        AppError: Si el prompt base del supervisor no se puede cargar (fichero ausente).
    """
    deps = Deps(
        llm=llm,
        context_reader=context_reader,
        allowed_bots=allowed_bots,
        appointments_graph=appointments_graph,
        orders_graph=orders_graph,
        faq_graph=faq_graph,
        draft_store=draft_store,
        confirmer=confirmer,
    )
    graph = StateGraph(SupervisorState)  # pyrefly: ignore[bad-specialization]
    graph.add_node("load_context", partial(load_context, deps=deps))
    graph.add_node("resolve_pending", partial(resolve_pending, deps=deps))
    graph.add_node("classify", partial(classify, deps=deps))
    graph.add_node("decide", partial(decide, deps=deps))
    graph.add_node("greet", greet)
    graph.add_node("route_appointments", partial(route_appointments, deps=deps))
    graph.add_node("route_orders", partial(route_orders, deps=deps))
    graph.add_node("route_faq", partial(route_faq, deps=deps))
    graph.add_node("route_pending", route_pending)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "resolve_pending")
    graph.add_conditional_edges(
        "resolve_pending",
        ruta_tras_pendiente,
        {"classify": "classify", "end": END},
    )
    graph.add_edge("classify", "decide")
    graph.add_conditional_edges(
        "decide",
        partial(ruta_tras_decidir, deps=deps),
        {
            "greet": "greet",
            "route_appointments": "route_appointments",
            "route_orders": "route_orders",
            "route_faq": "route_faq",
            "route_pending": "route_pending",
            "end": END,
        },
    )
    graph.add_edge("greet", END)
    graph.add_edge("route_appointments", END)
    graph.add_edge("route_orders", END)
    graph.add_edge("route_faq", END)
    graph.add_edge("route_pending", END)
    return graph.compile()
