"""Grafo del supervisor: nodos, aristas y compilación (ROADMAP Paso 4).

Orden: `load_context` → `classify` → `decide` → [greet | route_appointments |
route_orders | route_pending | fin]. El saludo y las respuestas degradadas terminan en
el propio supervisor; las citas y los pedidos se ejecutan invocando su grafo ya
compilado (nodo anidado, ADR 0010) y el resto deja el `RoutedTurn` para cuando existan
esos grafos (el de pedidos es opcional hasta que la composición lo inyecte).

Las dependencias llegan por `partial` (DI manual): quien construye el grafo decide si
el LLM es Bedrock o un doble, quién lee el contexto de cliente y con qué entitlements
corre cada comercio.
"""

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from shared.contracts import AgentName
from shared.ports import LLMPort
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.nodes import (
    classify,
    decide,
    greet,
    load_context,
    route_appointments,
    route_orders,
    route_pending,
    ruta_tras_decidir,
)
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.ports import ContextReaderPort, SpecialistGraphPort


# Nota pyrefly: mismo caso que `appointments/application/graph.py` — `TypedDict` no pasa
# el bound `StateLike` de langgraph; mypy y el runtime sí (lo ejecutan los tests).
def build_supervisor_graph(
    *,
    llm: LLMPort,
    context_reader: ContextReaderPort,
    allowed_bots: frozenset[AgentName],
    appointments_graph: SpecialistGraphPort,
    orders_graph: SpecialistGraphPort | None = None,
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
    )
    graph = StateGraph(SupervisorState)  # pyrefly: ignore[bad-specialization]
    graph.add_node("load_context", partial(load_context, deps=deps))
    graph.add_node("classify", partial(classify, deps=deps))
    graph.add_node("decide", partial(decide, deps=deps))
    graph.add_node("greet", greet)
    graph.add_node("route_appointments", partial(route_appointments, deps=deps))
    graph.add_node("route_orders", partial(route_orders, deps=deps))
    graph.add_node("route_pending", route_pending)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "classify")
    graph.add_edge("classify", "decide")
    graph.add_conditional_edges(
        "decide",
        partial(ruta_tras_decidir, deps=deps),
        {
            "greet": "greet",
            "route_appointments": "route_appointments",
            "route_orders": "route_orders",
            "route_pending": "route_pending",
            "end": END,
        },
    )
    graph.add_edge("greet", END)
    graph.add_edge("route_appointments", END)
    graph.add_edge("route_orders", END)
    graph.add_edge("route_pending", END)
    return graph.compile()
