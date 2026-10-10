"""Nodos del grafo faq: funciones puras sobre `AgentState` con DI.

Cada nodo recibe el estado completo y devuelve el estado con el trozo que escribe;
LangGraph lo fusiona con el estado anterior. El orden y las aristas viven en
`application/graph.py` (ROADMAP Paso 7). Los nodos no crean nada: el LLM y la
tool `search_knowledge` llegan en `Deps`.
"""

from slices.knowledge_rag.application.nodes.fallback import fallback
from slices.knowledge_rag.application.nodes.respond import respond
from slices.knowledge_rag.application.nodes.retrieve import retrieve
from slices.knowledge_rag.application.state import AgentState

__all__ = ["fallback", "respond", "retrieve", "ruta_tras_recuperar"]


def ruta_tras_recuperar(state: AgentState) -> str:
    """Arista condicional tras `retrieve`: respuesta fundamentada o fallback.

    Args:
        state: Estado con `evidence` (hubo chunks por encima del umbral) o con
            `fallback_reason` (sin evidencia o almacén caído).

    Returns:
        `"respond"` si hay evidencia; `"fallback"` en caso contrario.
    """
    return "fallback" if state.get("fallback_reason") else "respond"
