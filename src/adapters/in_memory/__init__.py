"""Dobles en memoria de puertos compartidos (sin servicios externos, Pasos 5 y 7)."""

from adapters.in_memory.drafts import InMemoryDraftStore
from adapters.in_memory.embeddings import InMemoryEmbeddings
from adapters.in_memory.vector import InMemoryVectorStore

__all__ = ["InMemoryDraftStore", "InMemoryEmbeddings", "InMemoryVectorStore"]
