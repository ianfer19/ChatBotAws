"""La tool `search_knowledge`: recuperación fundamentada sobre puertos inyectados.

La tool no acepta el comercio del LLM: el `tenant_id` siempre llega del estado
del turno (contexto resuelto en el gateway) y es el único filtro que usa el
almacén — jamás se infiere del payload. Sin evidencia por encima del umbral se
lanza `NoEvidenceFound` (el especialista responde el fallback, nunca inventa);
si embeddings o almacén fallan, `VectorStoreUnavailable` degrada el turno sin
romperlo. Todo se loguea con `correlation_id` y `tenant_id`, sin el texto de la
consulta (puede contener PII).
"""

from shared.errors import ToolError, ValidationError
from shared.logging import get_logger
from shared.ports import EmbeddingsPort, VectorHit, VectorStorePort
from slices.knowledge_rag.application.schemas import ToolResult
from slices.knowledge_rag.domain.errors import NoEvidenceFound, VectorStoreUnavailable
from slices.knowledge_rag.domain.rules import DEFAULT_TOP_K, SIMILITUDE_THRESHOLD, select_evidence

_logger = get_logger(__name__)


class KnowledgeTools:
    """Implementación de `search_knowledge` sobre embeddings y almacén vectorial.

    Example:
        >>> from adapters.in_memory import InMemoryEmbeddings, InMemoryVectorStore
        >>> tools = KnowledgeTools(
        ...     embeddings=InMemoryEmbeddings(), store=InMemoryVectorStore()
        ... )
        >>> tools._threshold
        0.35
    """

    def __init__(
        self,
        *,
        embeddings: EmbeddingsPort,
        store: VectorStorePort,
        threshold: float = SIMILITUDE_THRESHOLD,
    ) -> None:
        """Guarda los puertos con los que trabaja cada consulta.

        Args:
            embeddings: Vectorizador (el mismo modelo usado en la ingesta).
            store: Almacén vectorial filtrado por tenant.
            threshold: Umbral de similitud de esta composición (los evals lo
                calibran, `TODO(verify)`).
        """
        self._embeddings = embeddings
        self._store = store
        self._threshold = threshold

    def search_knowledge(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        query: str,
        top_k: int = DEFAULT_TOP_K,
    ) -> ToolResult:
        """Recupera la evidencia del conocimiento del comercio para una consulta.

        Args:
            tenant_id: Comercio resuelto en el gateway; obligatorio.
            correlation_id: Clave de trazabilidad del turno; obligatoria (logs).
            query: Texto a buscar (pregunta del cliente, sin PII en los logs).
            top_k: Candidatos a recuperar (4-8, `TODO(verify)` con evals).

        Returns:
            `ToolResult` con al menos una evidencia ya filtrada por umbral.

        Raises:
            ValidationError: Si falta `tenant_id`, `correlation_id` o `query`.
            NoEvidenceFound: Si ningún candidato supera el umbral (fallback).
            VectorStoreUnavailable: Si los embeddings o el almacén fallan.
        """
        if not tenant_id:
            raise ValidationError("tenant_id vacío en search_knowledge")
        if not correlation_id:
            raise ValidationError("correlation_id vacío en search_knowledge")
        if not query.strip():
            raise ValidationError("query vacía en search_knowledge")

        vector = self._embedir(query=query, tenant_id=tenant_id, correlation_id=correlation_id)
        hits = self._buscar(
            vector=vector, tenant_id=tenant_id, correlation_id=correlation_id, top_k=top_k
        )
        try:
            evidence = select_evidence(hits, threshold=self._threshold, top_k=top_k)
        except NoEvidenceFound:
            _logger.info(
                "knowledge_rag.sin_evidencia",
                extra={"tenant_id": tenant_id, "correlation_id": correlation_id},
            )
            raise
        _logger.info(
            "knowledge_rag.evidencia",
            extra={
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "evidence": len(evidence),
                "top_score": evidence[0].score,
            },
        )
        return ToolResult(tool="search_knowledge", evidence=evidence)

    def _embedir(self, *, query: str, tenant_id: str, correlation_id: str) -> list[float]:
        """Vectoriza la consulta con el mismo modelo de la ingesta.

        Args:
            query: Texto del cliente a embeber.
            tenant_id: Comercio del turno (para los logs de fallo).
            correlation_id: Trazabilidad del turno (para los logs de fallo).

        Returns:
            El embedding de la consulta.

        Raises:
            VectorStoreUnavailable: Si el modelo de embeddings falla o expira.
        """
        try:
            vectores = self._embeddings.embed(texts=[query])
        except ToolError as exc:
            _logger.error(
                "knowledge_rag.embeddings_fallaron",
                extra={"tenant_id": tenant_id, "correlation_id": correlation_id},
            )
            raise VectorStoreUnavailable("no se pudo vectorizar la consulta") from exc
        return list(vectores[0])

    def _buscar(
        self, *, vector: list[float], tenant_id: str, correlation_id: str, top_k: int
    ) -> list[VectorHit]:
        """Consulta el almacén solo con el tenant del turno.

        Args:
            vector: Embedding de la consulta.
            tenant_id: Comercio del turno (filtro obligatorio del port).
            correlation_id: Trazabilidad del turno.
            top_k: Máximo de candidatos.

        Returns:
            Vecinos más parecidos del propio tenant (puede venir vacío).

        Raises:
            VectorStoreUnavailable: Si el almacén falla o expira.
        """
        try:
            return list(self._store.search(vector=vector, tenant_id=tenant_id, limit=top_k))
        except ToolError as exc:
            _logger.error(
                "knowledge_rag.almacen_no_disponible",
                extra={"tenant_id": tenant_id, "correlation_id": correlation_id},
            )
            raise VectorStoreUnavailable("almacen vectorial no disponible") from exc
