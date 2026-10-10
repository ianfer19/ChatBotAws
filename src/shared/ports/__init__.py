"""Ports transversales (Protocol): modelo, canales Meta, vectorial, memoria, drafts y más.

El kernel declara QUÉ necesita el sistema; las implementaciones concretas viven en
`adapters/` (transversales) o en la `infrastructure/` de cada slice (propias).
"""

from shared.ports.base import ClockPort, EventBusPort
from shared.ports.channel import ChannelMessage, ChannelPort, MessageType
from shared.ports.draft import DraftStorePort
from shared.ports.embeddings import EmbeddingsPort
from shared.ports.llm import LLMMessage, LLMPort, LLMResult
from shared.ports.memory import MemoryStorePort
from shared.ports.vector import VectorHit, VectorRecord, VectorStorePort

__all__ = [
    "ChannelMessage",
    "ChannelPort",
    "ClockPort",
    "DraftStorePort",
    "EmbeddingsPort",
    "EventBusPort",
    "LLMMessage",
    "LLMPort",
    "LLMResult",
    "MemoryStorePort",
    "MessageType",
    "VectorHit",
    "VectorRecord",
    "VectorStorePort",
]
