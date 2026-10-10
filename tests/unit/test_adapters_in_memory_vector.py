"""Dobles en memoria de los puertos vectoriales (Paso 7): aislamiento y determinismo.

Prueban `InMemoryVectorStore` e `InMemoryEmbeddings` de `adapters/in_memory`,
el mismo doble que usan los tests de ingesta y de la tool `search_knowledge`.
"""

import pytest

from adapters.in_memory import InMemoryEmbeddings, InMemoryVectorStore
from adapters.in_memory.vector import _cosine
from shared.errors import ValidationError
from shared.ports import VectorRecord, VectorStorePort


def _record(*, tenant_id: str, identificador: str, text: str, vector: list[float]) -> VectorRecord:
    """Registro de prueba para el store.

    Args:
        tenant_id: Comercio dueño.
        identificador: Id del registro.
        text: Texto del chunk.
        vector: Embedding ya calculado.

    Returns:
        El registro validado.
    """
    return VectorRecord(
        id=identificador,
        tenant_id=tenant_id,
        text=text,
        vector=vector,
        metadata={"source_type": "faq", "source_id": "faq-1"},
    )


def test_es_un_vector_store_port() -> None:
    """El doble satisface el Protocol que exige la aplicación."""
    assert isinstance(InMemoryVectorStore(), VectorStorePort)


def test_upsert_es_idempotente_por_tenant_e_id() -> None:
    """Reescribir el mismo id reemplaza el registro; no duplica entradas."""
    store = InMemoryVectorStore()
    store.upsert(
        records=[_record(tenant_id="t1", identificador="c1", text="v1", vector=[1.0, 0.0])]
    )
    store.upsert(
        records=[_record(tenant_id="t1", identificador="c1", text="v2", vector=[0.0, 1.0])]
    )
    hits = store.search(vector=[0.0, 1.0], tenant_id="t1", limit=10)
    assert len(hits) == 1
    assert hits[0].text == "v2"


def test_search_solo_devuelve_del_tenant_pedido() -> None:
    """El mismo id existe en dos comercios y cada uno ve solo el suyo."""
    store = InMemoryVectorStore()
    store.upsert(
        records=[
            _record(tenant_id="t1", identificador="c1", text="de t1", vector=[1.0, 0.0]),
            _record(tenant_id="t2", identificador="c1", text="de t2", vector=[1.0, 0.0]),
        ]
    )
    assert [hit.text for hit in store.search(vector=[1.0, 0.0], tenant_id="t1")] == ["de t1"]
    assert [hit.text for hit in store.search(vector=[1.0, 0.0], tenant_id="t2")] == ["de t2"]


def test_search_ordena_por_similitud_y_respeta_el_limit() -> None:
    """El más parecido va primero y `limit` recorta la cola."""
    store = InMemoryVectorStore()
    store.upsert(
        records=[
            _record(tenant_id="t1", identificador="lejos", text="lejos", vector=[0.0, 1.0]),
            _record(tenant_id="t1", identificador="cerca", text="cerca", vector=[1.0, 0.1]),
            _record(tenant_id="t1", identificador="medio", text="medio", vector=[0.7, 0.7]),
        ]
    )
    hits = store.search(vector=[1.0, 0.0], tenant_id="t1", limit=2)
    assert [hit.id for hit in hits] == ["cerca", "medio"]
    assert hits[0].score >= hits[1].score


def test_delete_no_toca_los_registros_de_otro_tenant() -> None:
    """Borrar el id en un comercio deja intacto el registro homónimo del otro."""
    store = InMemoryVectorStore()
    store.upsert(
        records=[
            _record(tenant_id="t1", identificador="c1", text="de t1", vector=[1.0, 0.0]),
            _record(tenant_id="t2", identificador="c1", text="de t2", vector=[1.0, 0.0]),
        ]
    )
    store.delete(tenant_id="t1", ids=["c1"])
    assert store.search(vector=[1.0, 0.0], tenant_id="t1") == []
    assert [hit.text for hit in store.search(vector=[1.0, 0.0], tenant_id="t2")] == ["de t2"]


def test_search_sin_tenant_es_error() -> None:
    """Buscar a ciegas está prohibido (regla 1 del slice)."""
    with pytest.raises(ValidationError):
        InMemoryVectorStore().search(vector=[1.0], tenant_id="")


def test_delete_sin_tenant_es_error() -> None:
    """Borrar a ciegas también: nunca se opera sin saber de quién es."""
    with pytest.raises(ValidationError):
        InMemoryVectorStore().delete(tenant_id="", ids=["c1"])


def test_upsert_sin_tenant_es_error() -> None:
    """Un registro huérfano no entra al almacén (aunque el dto no lo valide)."""
    huerfano = VectorRecord.model_construct(
        id="c1", tenant_id="", text="x", vector=[1.0], metadata={}
    )
    with pytest.raises(ValidationError):
        InMemoryVectorStore().upsert(records=[huerfano])


def test_embeddings_son_deterministas() -> None:
    """El mismo texto produce siempre el mismo vector (ingesta y consulta coinciden)."""
    emb = InMemoryEmbeddings()
    primero = emb.embed(texts=["horario de apertura"])
    segundo = emb.embed(texts=["horario de apertura"])
    assert list(primero[0]) == list(segundo[0])


def test_embeddings_de_un_texto_igual_son_identicos_y_normalizados() -> None:
    """Vector L2-normalizado: el coseno de un texto consigo mismo es 1."""
    emb = InMemoryEmbeddings()
    vector = list(emb.embed(texts=["paella de mariscos"])[0])
    norma = sum(valor * valor for valor in vector) ** 0.5
    assert abs(norma - 1.0) < 1e-9


def test_textos_con_palabras_en_comun_quedan_mas_parecidos() -> None:
    """La similitud del doble refleja el solapamiento léxico (base de los tests)."""
    emb = InMemoryEmbeddings()
    base = emb.embed(texts=["horario de apertura de lunes"])[0]
    parecido = emb.embed(texts=["horario de apertura"])[0]
    distante = emb.embed(texts=["politica de envios nacionales"])[0]
    assert _cosine(base, parecido) > _cosine(base, distante)


def test_texto_sin_palabras_da_vector_cero() -> None:
    """Sin tokens alfanuméricos el vector es cero (coseno 0, jamás NaN)."""
    emb = InMemoryEmbeddings()
    vector = emb.embed(texts=["!!! ??? ..."])[0]
    assert all(valor == 0.0 for valor in vector)
