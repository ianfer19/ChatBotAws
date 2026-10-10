"""Dobles en memoria de los ports de conocimiento (Paso 7; sin Aurora ni legacy).

`InMemoryKnowledgeSource` simula la fuente de documentos (catálogo/FAQ/policy)
y `InMemoryDocumentRegistry` la tabla `documents` (hash e ids de chunks). Los
tests de ingesta y el REPL los usan hasta que lleguen los adapters reales
(HTTP del legacy: `TODO(verify)` en el Paso 11; Aurora: `adapters/aurora`).
"""

from collections.abc import Sequence

from shared.errors import ValidationError
from slices.knowledge_rag.domain.entities import SourceDocument, StoredDocument


class InMemoryKnowledgeSource:
    """Fuente de documentos en memoria, filtrable por tenant.

    Example:
        >>> fuente = InMemoryKnowledgeSource()
        >>> fuente.add_document(
        ...     SourceDocument(
        ...         tenant_id="Sede_Elite_01",
        ...         source_type="faq",
        ...         source_id="faq-1",
        ...         content="Horario: abrimos de lunes a sabado.",
        ...     )
        ... )
        >>> len(fuente.fetch_documents(tenant_id="Sede_Elite_01"))
        1
        >>> fuente.fetch_documents(tenant_id="Otro_Comercio_02")
        []
    """

    def __init__(self, documents: Sequence[SourceDocument] = ()) -> None:
        """Crea la fuente con los documentos iniciales.

        Args:
            documents: Documentos sembrados (pueden ser de varios tenants).
        """
        self._documents = list(documents)

    def add_document(self, document: SourceDocument) -> None:
        """Añade un documento a la fuente (para tests y semillas del REPL).

        Args:
            document: Documento crudo de cualquier tenant.
        """
        self._documents.append(document)

    def fetch_documents(self, *, tenant_id: str) -> Sequence[SourceDocument]:
        """Devuelve solo los documentos del tenant indicado (regla de la fuente).

        Args:
            tenant_id: Comercio cuyo conocimiento se pide; obligatorio.

        Returns:
            Documentos de ese tenant, en orden de inserción.

        Raises:
            ValidationError: Si `tenant_id` está vacío.
        """
        if not tenant_id:
            raise ValidationError("tenant_id vacío en la fuente de conocimiento")
        return [d for d in self._documents if d.tenant_id == tenant_id]


class InMemoryDocumentRegistry:
    """Tabla `documents` en memoria: hash e ids de chunks por fuente y tenant.

    Example:
        >>> registro = InMemoryDocumentRegistry()
        >>> registro.get_document(tenant_id="Sede_Elite_01", source_id="faq-1") is None
        True
        >>> registro.save_document(
        ...     tenant_id="Sede_Elite_01",
        ...     source_id="faq-1",
        ...     document=StoredDocument(content_hash="abc", chunk_ids=("c1",)),
        ... )
        >>> registro.get_document(
        ...     tenant_id="Sede_Elite_01", source_id="faq-1"
        ... ).chunk_ids
        ('c1',)
    """

    def __init__(self) -> None:
        """Crea el registro vacío (clave compuesta de tenant y fuente)."""
        self._documents: dict[tuple[str, str], StoredDocument] = {}

    def get_document(self, *, tenant_id: str, source_id: str) -> StoredDocument | None:
        """Recupera el estado de indexación de una fuente del tenant.

        Args:
            tenant_id: Comercio dueño del documento.
            source_id: Id de la fuente.

        Returns:
            El registro conocido o `None` si nunca se ingerió.
        """
        return self._documents.get((tenant_id, source_id))

    def save_document(self, *, tenant_id: str, source_id: str, document: StoredDocument) -> None:
        """Guarda (o reemplaza) el estado de indexación de una fuente.

        Args:
            tenant_id: Comercio dueño del documento.
            source_id: Id de la fuente.
            document: Hash e ids de chunks de la corrida.

        Raises:
            ValidationError: Si falta tenant o fuente.
        """
        if not tenant_id or not source_id:
            raise ValidationError("registro de documentos sin tenant o source_id")
        self._documents[(tenant_id, source_id)] = document
