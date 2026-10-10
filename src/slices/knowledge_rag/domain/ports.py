"""Ports que el dominio de conocimiento consume (Paso 7).

`KnowledgeSourcePort` es la fuente de la ingesta: hoy existe como doble en
memoria (tests/REPL) y el adapter HTTP contra el backend legacy queda
`TODO(verify)` hasta el Paso 11 (AgentCore Gateway). `DocumentRegistryPort` es
la tabla `documents` de DATA_MODEL (hash + ids de chunks por fuente) y da a la
re-ingesta su idempotencia. El almacén vectorial y los embeddings llegan de
`shared/ports/` (`VectorStorePort`, `EmbeddingsPort`).
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .entities import SourceDocument, StoredDocument


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


@runtime_checkable
class DocumentRegistryPort(Protocol):
    """Registro de documentos ingeridos: hash de contenido e ids de chunks."""

    def get_document(self, *, tenant_id: str, source_id: str) -> StoredDocument | None:
        """Recupera el estado de indexación de una fuente del tenant.

        Args:
            tenant_id: Comercio dueño del documento.
            source_id: Id de la fuente en el backend legacy.

        Returns:
            El registro conocido, o `None` si la fuente nunca se ingerió.

        Raises:
            ToolError: Si el registro no responde (lo traduce el adapter).
        """
        ...

    def save_document(self, *, tenant_id: str, source_id: str, document: StoredDocument) -> None:
        """Guarda (o reemplaza) el estado de indexación de una fuente.

        Args:
            tenant_id: Comercio dueño del documento.
            source_id: Id de la fuente en el backend legacy.
            document: Hash e ids de chunks resultantes de la corrida.

        Raises:
            ToolError: Si el registro no admite la escritura.
        """
        ...
