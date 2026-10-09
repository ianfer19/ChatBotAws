"""Grafo de citas de LangGraph: nodos, aristas y compilación (ROADMAP Paso 3).

Orden del diagrama del ROADMAP: `understand` → `validate` → `need_more?` →
`select_action` → `call_tool` → `validate_result` → `needs_confirmation?` → `respond` →
`END`. No hay checkpointer todavía: la persistencia entre turnos llega con el Paso 8
(`TODO(decision)`).

Los nodos reciben sus dependencias por `partial` (DI manual): quien construye el grafo
decide si el LLM es Bedrock o un doble de test, y si el repositorio es memoria o
DynamoDB (Paso 6).
"""

from collections.abc import Sequence
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from shared.ports import ClockPort, DraftStorePort, LLMPort
from slices.appointments.application.deps import Deps
from slices.appointments.application.nodes import (
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
from slices.appointments.application.schemas import OpeningHoursDay, ToolName
from slices.appointments.application.state import AgentState
from slices.appointments.application.tools import AppointmentTools
from slices.appointments.domain.ports import AppointmentRepositoryPort


# Nota pyrefly: `AgentState` (TypedDict) no pasa el bound `StateLike` de langgraph:
# pyrefly ve `TypedDict.__required_keys__` sin `ClassVar` (falla el protocolo V1) y
# rechaza atributos de cuerpo de clase sin `ClassVar` en objetos-clase (falla el V2).
# mypy y el runtime de langgraph sí aceptan este grafo (lo ejecutan los tests), así que
# los dos `ignore` de este fichero son solo para pyrefly.
def build_appointment_graph(
    *,
    llm: LLMPort,
    repo: AppointmentRepositoryPort,
    clock: ClockPort,
    opening_hours: Sequence[OpeningHoursDay],
    drafts: DraftStorePort,
    allowed_tools: frozenset[ToolName] | None = None,
) -> CompiledStateGraph[AgentState, Any, Any, Any]:  # pyrefly: ignore[bad-specialization]
    """Construye y compila el grafo de citas con las dependencias del entorno.

    Args:
        llm: Modelo de lenguaje (`BedrockLLM` en producción, doble guionizado en tests).
        repo: Repositorio de citas (en memoria hasta el Paso 6).
        clock: Reloj inyectable para descartar huecos pasados.
        opening_hours: Horario de atención del comercio (falso hasta RAG/Paso 7).
        drafts: Store de propuestas pendientes (ADR 0011; `InMemoryDraftStore` en
            desarrollo, DynamoDB `pending_actions` en el Paso 6).
        allowed_tools: Entitlements finos del comercio (Fase 4 del Paso 5); `None`
            permite toda la allowlist del slice.

    Returns:
        Grafo compilado, listo para `invoke` con un estado inicial `AgentState`.

    Raises:
        AppError: Si el prompt base de citas no se puede cargar (fichero ausente).
    """
    deps = Deps(
        llm=llm,
        tools=AppointmentTools(repo=repo, clock=clock, opening_hours=opening_hours, drafts=drafts),
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
