"""Ports transversales (Protocol): modelo, vectorial, memoria, drafts, reloj y eventos.

El kernel declara QUÉ necesita el sistema; las implementaciones concretas viven en
`adapters/` (transversales) o en la `infrastructure/` de cada slice (propias).
"""

from shared.ports.base import ClockPort, EventBusPort
from shared.ports.draft import DraftStorePort
from shared.ports.embeddings import EmbeddingsPort
from shared.ports.llm import LLMMessage, LLMPort, LLMResult
from shared.ports.memory import MemoryStorePort
from shared.ports.vector import VectorHit, VectorRecord, VectorStorePort

__all__ = [
    "ClockPort",
    "DraftStorePort",
    "EmbeddingsPort",
    "EventBusPort",
    "LLMMessage",
    "LLMPort",
    "LLMResult",
    "MemoryStorePort",
    "VectorHit",
    "VectorRecord",
    "VectorStorePort",
]
