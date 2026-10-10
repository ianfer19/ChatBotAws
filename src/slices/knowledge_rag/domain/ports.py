"""Ports que el dominio de conocimiento consume (Paso 7).

`KnowledgeSourcePort` es la fuente de la ingesta: hoy existe como doble en
memoria (tests/REPL) y el adapter HTTP contra el backend legacy queda
`TODO(verify)` hasta el Paso 11 (AgentCore Gateway). El almacén vectorial y los
embeddings llegan de `shared/ports/` (`VectorStorePort`, `EmbeddingsPort`).
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .entities import SourceDocument


@runtime_checkable
class KnowledgeSourcePort(Protocol):
    """Fuente de documentos de conocimiento de un comercio."""

    def fetch_documents(self, *, tenant_id: str) -> Sequence[SourceDocument]:
        """Devuelve los documentos a ingerir del tenant indicado.

        Args:
            tenant_id: Comercio cuyo conocimiento se ingerí; jamás se infiere
                del payload de un LLM (MULTI_TENANCY §5).

        Returns:
            Documentos crudos; la validación de origen y el chunking ocurren
            en el pipeline de ingesta, no en la fuente.

        Raises:
            ToolError: Si la fuente falla (lo traduce el adapter).
            ToolTimeoutError: Si la fuente excede su timeout.
        """
        ...
