"""Estado del grafo de respuestas de conocimiento (`AgentState`), ROADMAP Paso 7.

Los tres primeros campos los pone el llamador (el nodo `route_faq` del supervisor)
con el contexto ya resuelto en el gateway — nunca con lo que el LLM escriba. El
resto lo escriben los nodos a medida que avanza el grafo, por eso son opcionales
(`NotRequired`) hasta que el nodo correspondiente se ejecuta.
"""

from typing import NotRequired, TypedDict

from shared.contracts.rag import EvidenceChunk
from shared.ports import LLMMessage
from slices.knowledge_rag.domain.rules import FallbackReason


class AgentState(TypedDict):
    """Estado tipado compartido por todos los nodos del grafo faq.

    Campos:
        tenant_id: Comercio resuelto en el gateway (contexto, no del LLM).
        correlation_id: Identificador del turno para logs.
        user_message: Texto del mensaje actual del cliente (la pregunta a buscar).
        history: Ventana de historial ya recortada (la pone el supervisor).
        evidence: Chunks recuperados por `retrieve` (única base de la respuesta).
        fallback_reason: Motivo de degradación cuando no hubo evidencia utilizable.
        reply: Respuesta final para el cliente (fundamentada o fallback).
    """

    tenant_id: str
    correlation_id: str
    user_message: str
    history: NotRequired[list[LLMMessage]]
    evidence: NotRequired[list[EvidenceChunk]]
    fallback_reason: NotRequired[FallbackReason]
    reply: NotRequired[str]
