"""Grafo de respuestas de conocimiento (faq) de LangGraph: nodos y compilación.

Orden: `retrieve` → [evidencia | fallback?] → `respond` | `fallback` → `END`. Si
hay evidencia por encima del umbral, `respond` redacta citando la fuente; si no
(ningún chunk superó el umbral o el almacén está caído), `fallback` responde con
el mensaje del dominio **sin invocar al modelo** — el turno nunca inventa.

Los nodos reciben sus dependencias por `partial` (DI manual): quien construye el
grafo decide si el LLM es Bedrock o un doble de test, y si el almacén vectorial
es memoria o Aurora+pgvector.
"""

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from shared.ports import EmbeddingsPort, LLMPort, VectorStorePort
from slices.knowledge_rag.application.deps import Deps
from slices.knowledge_rag.application.nodes import fallback, respond, retrieve, ruta_tras_recuperar
from slices.knowledge_rag.application.state import AgentState
from slices.knowledge_rag.application.tools import KnowledgeTools
from slices.knowledge_rag.domain.rules import SIMILITUDE_THRESHOLD


# Nota pyrefly: `AgentState` (TypedDict) no pasa el bound `StateLike` de langgraph:
# pyrefly ve `TypedDict.__required_keys__` sin `ClassVar` (falla el protocolo V1) y
# rechaza atributos de cuerpo de clase sin `ClassVar` en objetos-clase (falla el V2).
# mypy y el runtime de langgraph sí aceptan este grafo (lo ejecutan los tests), así que
# los dos `ignore` de este fichero son solo para pyrefly.
def build_faq_graph(
    *,
    llm: LLMPort,
    embeddings: EmbeddingsPort,
    store: VectorStorePort,
    threshold: float = SIMILITUDE_THRESHOLD,
) -> CompiledStateGraph[AgentState, Any, Any, Any]:  # pyrefly: ignore[bad-specialization]
    """Construye y compila el grafo faq con las dependencias del entorno.

    Args:
        llm: Modelo de redacción (`BedrockLLM` en producción, doble guionizado
            en tests); solo se invoca en la rama con evidencia.
        embeddings: Vectorizador de la consulta (el mismo modelo de la ingesta).
        store: Almacén vectorial filtrado por tenant (`InMemoryVectorStore` en
            tests, `AuroraVectorStore` en producción).
        threshold: Umbral de similitud de esta composición (los evals lo calibran).

    Returns:
        Grafo compilado, listo para `invoke` con un estado inicial `AgentState`.

    Raises:
        AppError: Si el prompt base de FAQ no se puede cargar (fichero ausente).
    """
    deps = Deps(
        llm=llm,
        tools=KnowledgeTools(embeddings=embeddings, store=store, threshold=threshold),
    )
    graph = StateGraph(AgentState)  # pyrefly: ignore[bad-specialization]
    graph.add_node("retrieve", partial(retrieve, deps=deps))
    graph.add_node("respond", partial(respond, deps=deps))
    graph.add_node("fallback", fallback)

    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        ruta_tras_recuperar,
        {"respond": "respond", "fallback": "fallback"},
    )
    graph.add_edge("respond", END)
    graph.add_edge("fallback", END)
    return graph.compile()
