"""Pipeline de ingesta de conocimiento: valida, trocea, vectoriza y registra.

El LLM jamás escribe aquí: la fuente es un `KnowledgeSourcePort` y la escritura
pasa por `VectorStorePort` con el `tenant_id` siempre explícito (nunca inferido).
Re-ingesta idempotente por hash (RAG.md): un documento sin cambios se omite sin
re-vectorizar; uno cambiado reemplaza sus chunks (borrado de los ids anteriores
+ upsert de los nuevos). Los documentos con origen no permitido no se indexan
(`IngestValidationFailed`), pero no abortan la corrida del resto del tenant.
"""

import uuid

from shared.errors import ValidationError
from shared.logging import get_logger
from shared.ports import EmbeddingsPort, VectorStorePort
from shared.ports.vector import VectorRecord
from slices.knowledge_rag.application.schemas import IngestReport
from slices.knowledge_rag.domain.entities import SourceDocument, StoredDocument
from slices.knowledge_rag.domain.errors import IngestValidationFailed
from slices.knowledge_rag.domain.ports import DocumentRegistryPort, KnowledgeSourcePort
from slices.knowledge_rag.domain.rules import (
    chunk_document,
    compute_content_hash,
    validate_document,
)

_logger = get_logger(__name__)


def _chunk_id(*, tenant_id: str, source_id: str, position: int) -> str:
    """Id determinístico de un chunk: la misma posición siempre pisa la misma fila.

    Args:
        tenant_id: Comercio dueño del chunk.
        source_id: Id de la fuente documental.
        position: Posición del fragmento dentro del documento.

    Returns:
        Id estable y corto (dentro del límite de 128 del port vectorial).
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"chatbot:{tenant_id}:{source_id}:{position}").hex


class KnowledgeIngestor:
    """Corre la ingesta de un comercio sobre fuente, embeddings, store y registro.

    Example:
        >>> from adapters.in_memory import InMemoryEmbeddings, InMemoryVectorStore
        >>> from slices.knowledge_rag.infrastructure.in_memory import (
        ...     InMemoryDocumentRegistry,
        ...     InMemoryKnowledgeSource,
        ... )
        >>> fuente = InMemoryKnowledgeSource()
        >>> ingesta = KnowledgeIngestor(
        ...     source=fuente,
        ...     embeddings=InMemoryEmbeddings(),
        ...     store=InMemoryVectorStore(),
        ...     registry=InMemoryDocumentRegistry(),
        ... )
        >>> ingesta.ingest(tenant_id="Sede_Elite_01").documents
        0
    """

    def __init__(
        self,
        *,
        source: KnowledgeSourcePort,
        embeddings: EmbeddingsPort,
        store: VectorStorePort,
        registry: DocumentRegistryPort,
    ) -> None:
        """Guarda los puertos con los que trabaja cada corrida.

        Args:
            source: Fuente de documentos del comercio (doble en memoria hoy;
                HTTP del legacy `TODO(verify)` en el Paso 11).
            embeddings: Vectorizador (el mismo modelo que en la consulta).
            store: Almacén vectorial (`adapters/aurora` con pgvector).
            registry: Tabla `documents` (hash e ids de chunks por fuente).
        """
        self._source = source
        self._embeddings = embeddings
        self._store = store
        self._registry = registry

    def ingest(self, *, tenant_id: str) -> IngestReport:
        """Ingieren todo el conocimiento disponible del tenant indicado.

        Args:
            tenant_id: Comercio cuyo conocimiento se indexa; obligatorio.

        Returns:
            `IngestReport` con contadores (indexados, omitidos, rechazados,
            chunks escritos).

        Raises:
            ValidationError: Si `tenant_id` está vacío.
            ToolError: Si la fuente, los embeddings o el almacén fallan (los
                traduce cada adapter; la corrida se detiene en el primer fallo
                para no dejar el registro a medias).
        """
        if not tenant_id:
            raise ValidationError("tenant_id vacío en la ingesta de conocimiento")

        documents = self._source.fetch_documents(tenant_id=tenant_id)
        ingested = 0
        skipped = 0
        chunks_written = 0
        rejected: list[str] = []

        for document in documents:
            try:
                validate_document(document)
            except IngestValidationFailed:
                _logger.warning(
                    "knowledge_rag.ingest_rechazado",
                    extra={"tenant_id": tenant_id, "source_id": document.source_id},
                )
                rejected.append(document.source_id)
                continue

            content_hash = compute_content_hash(document.content)
            anterior = self._registry.get_document(
                tenant_id=tenant_id, source_id=document.source_id
            )
            if anterior is not None and anterior.content_hash == content_hash:
                skipped += 1
                continue

            chunks = chunk_document(document)
            vectores = self._embeddings.embed(texts=[c.text for c in chunks])
            records = [
                VectorRecord(
                    id=_chunk_id(
                        tenant_id=tenant_id,
                        source_id=document.source_id,
                        position=chunk.position,
                    ),
                    tenant_id=tenant_id,
                    text=chunk.text,
                    vector=list(vector),
                    metadata=_metadata_for(document),
                )
                for chunk, vector in zip(chunks, vectores, strict=True)
            ]
            if anterior is not None and anterior.chunk_ids:
                self._store.delete(tenant_id=tenant_id, ids=anterior.chunk_ids)
            self._store.upsert(records=records)
            self._registry.save_document(
                tenant_id=tenant_id,
                source_id=document.source_id,
                document=StoredDocument(
                    content_hash=content_hash,
                    chunk_ids=tuple(record.id for record in records),
                ),
            )
            ingested += 1
            chunks_written += len(records)

        _logger.info(
            "knowledge_rag.ingest",
            extra={
                "tenant_id": tenant_id,
                "documents": len(documents),
                "ingested": ingested,
                "skipped": skipped,
                "rejected": len(rejected),
                "chunks": chunks_written,
            },
        )
        return IngestReport(
            documents=len(documents),
            ingested=ingested,
            skipped=skipped,
            rejected=tuple(rejected),
            chunks=chunks_written,
        )


def _metadata_for(document: SourceDocument) -> dict[str, str]:
    """Arma el metadata de los chunks: lo que la respuesta necesita para citar.

    Args:
        document: Documento fuente ya validado.

    Returns:
        `source_type`, `source_id` y `title` (si existe) más el metadata heredado;
        son las claves que `select_evidence` exige para aceptar evidencia.
    """
    metadata = dict(document.metadata)
    metadata["source_type"] = document.source_type
    metadata["source_id"] = document.source_id
    if document.title:
        metadata["title"] = document.title
    return metadata
