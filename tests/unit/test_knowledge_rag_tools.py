"""Tool `search_knowledge`: evidencia, aislamiento por tenant y degradación (Paso 7).

Todo con dobles en memoria: el store se siembra directamente con la misma
vectorización determinista que usa la tool, sin AWS.
"""

from collections.abc import Sequence

import pytest

from adapters.in_memory import InMemoryEmbeddings, InMemoryVectorStore
from shared.errors import ToolError, ValidationError
from shared.ports import EmbeddingsPort, VectorHit, VectorRecord, VectorStorePort
from slices.knowledge_rag.application.tools import KnowledgeTools
from slices.knowledge_rag.domain.errors import NoEvidenceFound, VectorStoreUnavailable

_TENANT = "Sede_Elite_01"
_OTRO = "Otro_Comercio_02"

_DOC_A = "Horario de apertura: de lunes a sabado de 8am a 6pm."
_DOC_A2 = "Horario de atencion: de lunes a viernes de 9am a 5pm."
_DOC_B = "Politica de envios: enviamos a todo el pais en 24 horas."


def _indexar(
    store: InMemoryVectorStore, *, tenant_id: str, source_id: str, textos: Sequence[str]
) -> None:
    """Siembra el store con los textos del tenant (misma vectorización que la tool).

    Args:
        store: Almacén en memoria.
        tenant_id: Comercio dueño de los textos.
        source_id: Id de la fuente (para citar en la evidencia).
        textos: Fragmentos a indexar.
    """
    vectores = InMemoryEmbeddings().embed(texts=textos)
    store.upsert(
        records=[
            VectorRecord(
                id=f"{source_id}-{indice}",
                tenant_id=tenant_id,
                text=texto,
                vector=list(vector),
                metadata={
                    "source_type": "faq",
                    "source_id": source_id,
                    "title": "Conocimiento",
                },
            )
            for indice, (texto, vector) in enumerate(zip(textos, vectores, strict=True))
        ]
    )


def _herramientas() -> KnowledgeTools:
    """Tool real sobre un store sembrado con dos comercios aislados.

    Returns:
        `KnowledgeTools` listo para consultar (el tenant se pasa por llamada).
    """
    store = InMemoryVectorStore()
    _indexar(store, tenant_id=_TENANT, source_id="faq-a", textos=[_DOC_A, _DOC_A2])
    _indexar(store, tenant_id=_OTRO, source_id="faq-b", textos=[_DOC_B])
    return KnowledgeTools(embeddings=InMemoryEmbeddings(), store=store)


def test_devuelve_evidencia_del_propio_tenant() -> None:
    """La consulta encuentra la fuente del comercio, citada y con score en 0..1."""
    tools = _herramientas()
    resultado = tools.search_knowledge(
        tenant_id=_TENANT, correlation_id="corr-rag-1", query="horario de apertura"
    )
    assert resultado.tool == "search_knowledge"
    assert len(resultado.evidence) >= 1
    for chunk in resultado.evidence:
        assert chunk.source_type == "faq"
        assert chunk.source_id == "faq-a"
        assert "Horario" in chunk.text
        assert 0.0 <= chunk.score <= 1.0


def test_la_consulta_no_cruza_la_frontera_del_tenant() -> None:
    """El mismo texto sobre otro comercio no ve la evidencia ajena: fallback."""
    tools = _herramientas()
    with pytest.raises(NoEvidenceFound):
        tools.search_knowledge(
            tenant_id=_OTRO, correlation_id="corr-rag-2", query="horario de apertura"
        )


def test_sin_evidencia_lanza_y_loggea_sin_pii(caplog: pytest.LogCaptureFixture) -> None:
    """El fallback deja traza info con correlation_id y el nombre del evento."""
    tools = _herramientas()
    with (
        caplog.at_level("INFO"),
        pytest.raises(NoEvidenceFound),
    ):
        tools.search_knowledge(
            tenant_id=_OTRO,
            correlation_id="corr-sin-evid",
            query="horario de apertura",
        )
    eventos = [
        record for record in caplog.records if "knowledge_rag.sin_evidencia" in record.getMessage()
    ]
    assert eventos
    assert getattr(eventos[0], "correlation_id", None) == "corr-sin-evid"
    assert "horario" not in caplog.text


def test_con_evidencia_loggea_el_top_score(caplog: pytest.LogCaptureFixture) -> None:
    """La traza de éxito lleva cuánta evidencia llegó y su mejor score."""
    tools = _herramientas()
    with caplog.at_level("INFO"):
        tools.search_knowledge(
            tenant_id=_TENANT, correlation_id="corr-con-evid", query="horario de apertura"
        )
    eventos = [
        record for record in caplog.records if "knowledge_rag.evidencia" in record.getMessage()
    ]
    assert eventos
    assert getattr(eventos[0], "correlation_id", None) == "corr-con-evid"
    assert getattr(eventos[0], "evidence", 0) >= 1
    assert 0.0 <= getattr(eventos[0], "top_score", 0.0) <= 1.0


def test_top_k_acota_la_evidencia() -> None:
    """`top_k` manda: con 1 solo se queda con la mejor (la de mayor score)."""
    tools = _herramientas()
    resultado = tools.search_knowledge(
        tenant_id=_TENANT,
        correlation_id="corr-rag-3",
        query="horario de apertura",
        top_k=1,
    )
    assert len(resultado.evidence) == 1
    assert resultado.evidence[0].text == _DOC_A


def test_tenant_vacio_es_error() -> None:
    """Sin tenant no se consulta nada (la tool no infiere comercio)."""
    tools = _herramientas()
    with pytest.raises(ValidationError):
        tools.search_knowledge(tenant_id="", correlation_id="corr-rag-4", query="horario")


def test_correlation_id_vacio_es_error() -> None:
    """Todo evento lleva correlation_id: sin él, la tool no corre."""
    tools = _herramientas()
    with pytest.raises(ValidationError):
        tools.search_knowledge(tenant_id=_TENANT, correlation_id="", query="horario")


def test_query_vacia_es_error() -> None:
    """Consulta en blanco no dispara embeddings ni búsqueda."""
    tools = _herramientas()
    with pytest.raises(ValidationError):
        tools.search_knowledge(tenant_id=_TENANT, correlation_id="corr-rag-5", query="   ")


class _StoreRoto:
    """Doble que falla como lo haría Aurora caída (ToolError de adaptador)."""

    def upsert(self, *, records: Sequence[VectorRecord]) -> None:
        """Falla siempre (no se usa en la consulta)."""
        raise ToolError("store caido")

    def search(
        self, *, vector: Sequence[float], tenant_id: str, limit: int = 5
    ) -> Sequence[VectorHit]:
        """Falla siempre: simula pgvector inaccesible."""
        raise ToolError("store caido")

    def delete(self, *, tenant_id: str, ids: Sequence[str]) -> None:
        """Falla siempre (no se usa en la consulta)."""
        raise ToolError("store caido")


def test_almacen_caido_se_traduce_a_vector_store_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un fallo del almacén degrada el turno con error tipado y log error."""
    tools = KnowledgeTools(embeddings=InMemoryEmbeddings(), store=_StoreRoto())
    with (
        caplog.at_level("ERROR"),
        pytest.raises(VectorStoreUnavailable),
    ):
        tools.search_knowledge(tenant_id=_TENANT, correlation_id="corr-rag-6", query="horario")
    assert any(
        "knowledge_rag.almacen_no_disponible" in record.getMessage() for record in caplog.records
    )


class _EmbeddingsRoto:
    """Doble que falla como lo haría Bedrock embeddings caído."""

    @property
    def dimensions(self) -> int:
        """Dimensionalidad ficticia (la llamada nunca llega a funcionar)."""
        return 128

    def embed(self, *, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Falla siempre: simula el modelo de embeddings no disponible."""
        raise ToolError("bedrock embeddings caido")


def test_embeddings_caidos_se_traducen_a_vector_store_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Si no se puede vectorizar la consulta, el error también es tipado."""
    tools = KnowledgeTools(embeddings=_EmbeddingsRoto(), store=InMemoryVectorStore())
    with (
        caplog.at_level("ERROR"),
        pytest.raises(VectorStoreUnavailable),
    ):
        tools.search_knowledge(tenant_id=_TENANT, correlation_id="corr-rag-7", query="horario")
    assert any(
        "knowledge_rag.embeddings_fallaron" in record.getMessage() for record in caplog.records
    )


def test_los_dobles_satisfacen_los_puertos() -> None:
    """`KnowledgeTools` trabaja solo contra los Protocol del kernel."""
    assert isinstance(InMemoryVectorStore(), VectorStorePort)
    assert isinstance(InMemoryEmbeddings(), EmbeddingsPort)
