"""Dependencias inyectadas en los nodos del grafo faq (DI manual).

El constructor del grafo (`build_faq_graph`) recibe estos objetos y los reparte
con `partial`; quien construye el grafo decide si el LLM es Bedrock o un doble
y si el almacén vectorial es memoria o Aurora+pgvector (Paso 7).
"""

from dataclasses import dataclass

from shared.ports import LLMPort
from slices.knowledge_rag.application.tools import KnowledgeTools


@dataclass(frozen=True)
class Deps:
    """Lo que los nodos no pueden crear por sí mismos.

    Args:
        llm: Modelo de redacción (`BedrockLLM` en producción, doble en tests);
            solo se invoca cuando hay evidencia (el fallback no pasa por el LLM).
        tools: Tool `search_knowledge` con embeddings y almacén ya cableados.
    """

    llm: LLMPort
    tools: KnowledgeTools
