"""Pipeline de ingesta de `knowledge_rag`: idempotencia, reemplazo y anti-poisoning (Paso 7).

Todo con dobles en memoria: fuente, embeddings, almacén y registro. Sin AWS.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from adapters.in_memory import InMemoryEmbeddings, InMemoryVectorStore
from shared.errors import ValidationError
from slices.knowledge_rag.application.ingest import KnowledgeIngestor
from slices.knowledge_rag.domain.entities import SourceDocument
from slices.knowledge_rag.domain.errors import IngestValidationFailed
from slices.knowledge_rag.domain.rules import validate_document
from slices.knowledge_rag.infrastructure.in_memory import (
    InMemoryDocumentRegistry,
    InMemoryKnowledgeSource,
)

_TENANT = "Sede_Elite_01"
_OTRO = "Otro_Comercio_02"


class _EmbeddingsCuenta:
    """Doble que cuenta las llamadas al vectorizador real (prueba de idempotencia)."""

    def __init__(self) -> None:
        """Empieza con cero llamadas al vectorizar."""
        self.llamadas = 0
        self.textos = 0
        self._real = InMemoryEmbeddings()

    @property
    def dimensions(self) -> int:
        """Dimensionalidad delegada en el doble real."""
        return self._real.dimensions

    def embed(self, *, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Cuenta la llamada y delega en el doble real."""
        self.llamadas += 1
        self.textos += len(texts)
        return [list(vector) for vector in self._real.embed(texts=texts)]


@dataclass
class _Pipeline:
    """Componentes de una corrida de ingesta, ya conectados entre sí."""

    fuente: InMemoryKnowledgeSource
    embeddings: _EmbeddingsCuenta
    store: InMemoryVectorStore
    registro: InMemoryDocumentRegistry
    ingesta: KnowledgeIngestor


def _doc(**sobrescribir: object) -> SourceDocument:
    """Documento mínimo de la fuente.

    Args:
        sobrescribir: Campos a reemplazar (p. ej. `content`, `source_type`).

    Returns:
        El documento ya validado.
    """
    campos: dict[str, object] = {
        "tenant_id": _TENANT,
        "source_type": "faq",
        "source_id": "faq-1",
        "title": "Horario",
        "content": "Horario de apertura: de lunes a sabado.",
    }
    campos.update(sobrescribir)
    return SourceDocument.model_validate(campos)


def _pipeline(*, documentos: Sequence[SourceDocument] = ()) -> _Pipeline:
    """Arma la ingesta completa con dobles (fuente, embeddings, store, registro).

    Args:
        documentos: Documentos sembrados en la fuente.

    Returns:
        Los componentes conectados listos para usar en el test.
    """
    fuente = InMemoryKnowledgeSource(documentos)
    embeddings = _EmbeddingsCuenta()
    store = InMemoryVectorStore()
    registro = InMemoryDocumentRegistry()
    ingesta = KnowledgeIngestor(
        source=fuente,
        embeddings=embeddings,
        store=store,
        registry=registro,
    )
    return _Pipeline(
        fuente=fuente,
        embeddings=embeddings,
        store=store,
        registro=registro,
        ingesta=ingesta,
    )


def _ids_en_el_store(store: InMemoryVectorStore, tenant_id: str) -> set[str]:
    """Ids de todos los chunks indexados de un tenant (búsqueda sin umbral).

    Args:
        store: Almacén en memoria.
        tenant_id: Comercio a consultar.

    Returns:
        Conjunto de ids visibles para ese tenant.
    """
    consulta = InMemoryEmbeddings().embed(texts=["consulta"])[0]
    return {hit.id for hit in store.search(vector=consulta, tenant_id=tenant_id, limit=100)}


def test_ingesta_escribe_chunks_y_registra_el_hash() -> None:
    """La primera corrida indexa chunks y guarda hash e ids en el registro."""
    pipeline = _pipeline(documentos=(_doc(),))
    reporte = pipeline.ingesta.ingest(tenant_id=_TENANT)
    assert reporte.documents == 1
    assert reporte.ingested == 1
    assert reporte.chunks >= 1
    registro = pipeline.registro.get_document(tenant_id=_TENANT, source_id="faq-1")
    assert registro is not None
    assert len(registro.chunk_ids) == reporte.chunks
    assert _ids_en_el_store(pipeline.store, _TENANT) == set(registro.chunk_ids)


def test_reingesta_sin_cambios_no_vuelve_a_vectorizar() -> None:
    """Hash idéntico = omisión total: ni embed ni upsert (RAG.md)."""
    pipeline = _pipeline(documentos=(_doc(),))
    pipeline.ingesta.ingest(tenant_id=_TENANT)
    assert pipeline.embeddings.llamadas == 1

    reporte = pipeline.ingesta.ingest(tenant_id=_TENANT)
    assert reporte.skipped == 1
    assert reporte.ingested == 0
    assert reporte.chunks == 0
    assert pipeline.embeddings.llamadas == 1


def test_documento_cambiado_reemplaza_sus_chunks_viejos() -> None:
    """Contenido nuevo = borrar los ids obsoletos y escribir los nuevos.

    El id depende de la posición, no del texto: al acortar el documento, los
    chunks de las posiciones altas desaparecen del almacén (sin huérfanos) y
    la posición 0 se reescribe con el texto nuevo.
    """
    largo = ("Horario de apertura extendido. " * 80).strip()
    pipeline = _pipeline(documentos=(_doc(content=largo),))
    pipeline.ingesta.ingest(tenant_id=_TENANT)
    registro = pipeline.registro.get_document(tenant_id=_TENANT, source_id="faq-1")
    assert registro is not None
    viejos = set(registro.chunk_ids)
    assert len(viejos) > 1

    contenido_corto = "Horario de apertura: de lunes a sabado."
    pipeline.fuente.add_document(_doc(content=contenido_corto))
    reporte = pipeline.ingesta.ingest(tenant_id=_TENANT)
    assert reporte.skipped == 1
    assert reporte.ingested == 1
    assert reporte.chunks == 1

    nuevos = pipeline.registro.get_document(tenant_id=_TENANT, source_id="faq-1")
    assert nuevos is not None
    assert set(nuevos.chunk_ids) < viejos
    visibles = _ids_en_el_store(pipeline.store, _TENANT)
    assert visibles == set(nuevos.chunk_ids)
    assert not (viejos - set(nuevos.chunk_ids)) & visibles
    consulta = InMemoryEmbeddings().embed(texts=["horario"])[0]
    textos = [
        hit.text for hit in pipeline.store.search(vector=consulta, tenant_id=_TENANT, limit=10)
    ]
    assert textos == [contenido_corto]


def test_origen_no_permitido_se_rechaza_y_no_frena_al_resto() -> None:
    """Un documento de origen prohibido no se indexa; el resto del tenant sí."""
    valido = _doc()
    prohibido = _doc(source_type="review", source_id="rev-9", content="Reseña de usuario.")
    pipeline = _pipeline(documentos=(prohibido, valido))
    reporte = pipeline.ingesta.ingest(tenant_id=_TENANT)
    assert reporte.rejected == ("rev-9",)
    assert reporte.ingested == 1
    assert pipeline.registro.get_document(tenant_id=_TENANT, source_id="rev-9") is None
    assert "rev-9" not in _ids_en_el_store(pipeline.store, _TENANT)


def test_origen_no_permitido_no_llega_a_vectorizar() -> None:
    """El rechazo ocurre antes del embed: cero textos del documento prohibido."""
    pipeline = _pipeline(
        documentos=(
            _doc(source_type="review", source_id="rev-9", content="Reseña."),
            _doc(),
        )
    )
    pipeline.ingesta.ingest(tenant_id=_TENANT)
    # Solo se vectorizaron los chunks del documento permitido.
    assert pipeline.embeddings.llamadas == 1
    assert pipeline.embeddings.textos >= 1


def test_ingesta_solo_del_tenant_solicitado() -> None:
    """Indexar el comercio A no toca nada del comercio B."""
    documentos = (
        _doc(),
        _doc(tenant_id=_OTRO, source_id="faq-b", content="Envios en 24 horas."),
    )
    pipeline = _pipeline(documentos=documentos)
    pipeline.ingesta.ingest(tenant_id=_TENANT)
    assert pipeline.registro.get_document(tenant_id=_OTRO, source_id="faq-b") is None
    assert _ids_en_el_store(pipeline.store, _OTRO) == set()


def test_ingesta_sin_tenant_es_error() -> None:
    """Ninguna corrida trabaja a ciegas: tenant obligatorio."""
    pipeline = _pipeline()
    with pytest.raises(ValidationError):
        pipeline.ingesta.ingest(tenant_id="")


def test_los_ids_de_chunk_son_deterministas_entre_corridas() -> None:
    """La misma fuente produce los mismos ids en pipelines distintos (upsert estable)."""
    primero = _pipeline(documentos=(_doc(),))
    primero.ingesta.ingest(tenant_id=_TENANT)
    segundo = _pipeline(documentos=(_doc(),))
    segundo.ingesta.ingest(tenant_id=_TENANT)

    def _ids(pipeline: _Pipeline) -> tuple[str, ...]:
        registro = pipeline.registro.get_document(tenant_id=_TENANT, source_id="faq-1")
        assert registro is not None
        return registro.chunk_ids

    assert _ids(primero) == _ids(segundo)


def test_validate_document_directo_rechaza_el_origen_prohibido() -> None:
    """La regla del dominio también falla si se llama fuera del pipeline."""
    with pytest.raises(IngestValidationFailed):
        validate_document(_doc(source_type="review"))
