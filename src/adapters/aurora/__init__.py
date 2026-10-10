"""Adapter de Aurora PostgreSQL v2 + pgvector: SOLO consultas de conocimiento (RAG). Paso 7.

Se exportan la fábrica de conexiones (con la contraseña de Secrets Manager) y
`AuroraVectorStore`, el `VectorStorePort` sobre la tabla `knowledge_chunks`.
`AuroraDocumentRegistry` vive en `slices/knowledge_rag/infrastructure/aurora.py`
porque implementa un port del dominio de ese slice (regla de
`adapters/AGENTS.md`: los adapters no importan slices).
"""

from adapters.aurora.connection import AuroraConnectionFactory, ConnectionFactory
from adapters.aurora.vector import AuroraVectorStore

__all__ = ["AuroraConnectionFactory", "AuroraVectorStore", "ConnectionFactory"]
