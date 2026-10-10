"""Tests unitarios de `adapters.aurora.AuroraVectorStore`: SQL, tenant y errores.

Sin PostgreSQL real: un doble de conexión/cursor registra cada sentencia con sus
parámetros y devuelve las filas que cada test necesite. Lo que se verifica aquí
es lo que MULTI_TENANCY exige: **toda** operación lleva `tenant_id` y ninguna
consulta se emite sin él.
"""

import json
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

from adapters.aurora import AuroraVectorStore
from shared.errors import ToolError, ValidationError
from shared.ports import VectorHit, VectorRecord, VectorStorePort

_TENANT = "Sede_Elite_01"


class _CursorFalso:
    """Cursor que registra `(sql, params)` y devuelve filas fijas."""

    def __init__(
        self,
        filas: list[tuple[Any, ...]] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Prepara el cursor con las filas o el error de cada test.

        Args:
            filas: Filas que devolverán `fetchall`/`fetchone`.
            error: Excepción que lanzará `execute` (simula un fallo de PG).
        """
        self.ejecuciones: list[tuple[str, tuple[Any, ...]]] = []
        self._filas = filas if filas is not None else []
        self._error = error

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        """Registra la sentencia; lanza el error configurado si lo hay."""
        self.ejecuciones.append((query, params if params is not None else ()))
        if self._error is not None:
            raise self._error

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Devuelve todas las filas registradas."""
        return list(self._filas)

    def fetchone(self) -> tuple[Any, ...] | None:
        """Devuelve la primera fila registrada, o `None` si no hay."""
        return self._filas[0] if self._filas else None

    def __enter__(self) -> "_CursorFalso":
        """El cursor se usa como gestor de contexto, como el de psycopg."""
        return self

    def __exit__(self, *args: object) -> None:
        """Cierra el gestor sin propagar nada (los errores ya se lanzan antes)."""


class _ConexionFalsa:
    """Conexión que entrega el cursor falso y registra si se cerró."""

    def __init__(self, cursor: _CursorFalso) -> None:
        """Guarda el cursor que entregará cada `cursor()`.

        Args:
            cursor: Cursor falso compartido por la conexión.
        """
        self._cursor = cursor
        self.cerrada = False

    def cursor(self) -> _CursorFalso:
        """Devuelve el cursor falso."""
        return self._cursor

    def close(self) -> None:
        """Marca la conexión como cerrada (el adapter debe cerrarla siempre)."""
        self.cerrada = True


def _store(conexion: _ConexionFalsa) -> AuroraVectorStore:
    """Store con la fábrica apuntando a la conexión falsa (cast por mypy).

    Args:
        conexion: Conexión falsa que reutiliza el cursor de test.

    Returns:
        `AuroraVectorStore` listo para usar.
    """
    return AuroraVectorStore(connect=lambda: cast("Connection[tuple[Any, ...]]", conexion))


def _record(**sobrescribir: Any) -> VectorRecord:
    """Registro de prueba con id uuid válido (como la ingesta real).

    Args:
        sobrescribir: Campos a sobreescribir.

    Returns:
        El registro validado.
    """
    campos: dict[str, Any] = {
        "id": uuid4().hex,
        "tenant_id": _TENANT,
        "text": "Horario de apertura: de lunes a sabado.",
        "vector": [0.1, 0.2, 0.7],
        "metadata": {"source_type": "faq", "source_id": "faq-1", "title": "Horario"},
    }
    campos.update(sobrescribir)
    return VectorRecord.model_validate(campos)


def test_es_un_vector_store_port() -> None:
    """Debe satisfacer `VectorStorePort` (el mismo port que usa la tool)."""
    store = _store(_ConexionFalsa(_CursorFalso()))
    assert isinstance(store, VectorStorePort)


def test_upsert_lleva_tenant_uuid_vector_y_metadata() -> None:
    """Cada `INSERT ... ON CONFLICT` trae tenant primero y la conversión a uuid."""
    cursor = _CursorFalso()
    conexion = _ConexionFalsa(cursor)
    registro = _record()

    _store(conexion).upsert(records=[registro])

    sql, params = cursor.ejecuciones[0]
    assert "knowledge_chunks" in sql
    assert "ON CONFLICT" in sql
    assert params[0] == _TENANT
    assert params[1] == str(UUID(registro.id))
    assert params[2] == "faq"
    assert params[6].startswith("[")
    assert json.loads(params[7])["source_id"] == "faq-1"
    assert conexion.cerrada


def test_upsert_vacio_no_abre_consultas() -> None:
    """Nada que escribir = cero sentencias (y cero conexiones a abusar)."""
    cursor = _CursorFalso()
    _store(_ConexionFalsa(cursor)).upsert(records=[])
    assert cursor.ejecuciones == []


def test_upsert_sin_tenant_es_validation_error() -> None:
    """Un registro sin comercio no entra en la base (y no se consulta nada)."""
    cursor = _CursorFalso()
    registro = VectorRecord.model_construct(
        id=uuid4().hex, tenant_id="", text="x", vector=[1.0], metadata={}
    )
    with pytest.raises(ValidationError):
        _store(_ConexionFalsa(cursor)).upsert(records=[registro])
    assert cursor.ejecuciones == []


def test_upsert_con_id_no_uuid_es_validation_error() -> None:
    """El adapter no escribe ids que la columna uuid no podría recibir."""
    cursor = _CursorFalso()
    registro = _record(id="no-soy-uuid")
    with pytest.raises(ValidationError):
        _store(_ConexionFalsa(cursor)).upsert(records=[registro])
    assert cursor.ejecuciones == []


def test_search_filtra_por_tenant_y_ordena_por_distancia() -> None:
    """La sentencia trae `WHERE tenant_id`, `ORDER BY <=>` y `LIMIT` con params."""
    cursor = _CursorFalso(filas=[(_TENANT, str(uuid4()), "texto", {"source_type": "faq"}, 0.8)])
    hits = _store(_ConexionFalsa(cursor)).search(vector=[0.1, 0.2, 0.7], tenant_id=_TENANT, limit=3)

    sql, params = cursor.ejecuciones[0]
    assert "WHERE tenant_id = %s" in sql
    assert "ORDER BY" in sql and "<=>" in sql
    assert "LIMIT %s" in sql
    assert params[1] == _TENANT
    assert params[3] == 3
    assert hits[0].score == pytest.approx(0.8)
    assert len(hits[0].id) == 32


def test_search_normaliza_id_a_hex_y_clampea_el_score() -> None:
    """Los ids vuelven en hex (formato del port) y el score siempre vive en 0..1."""
    id_1, id_2 = uuid4(), uuid4()
    cursor = _CursorFalso(
        filas=[
            (_TENANT, str(id_1), "muy lejano", {}, -0.4),
            (_TENANT, str(id_2), "muy cercano", {}, 1.7),
        ]
    )
    hits = _store(_ConexionFalsa(cursor)).search(vector=[1.0], tenant_id=_TENANT)

    assert [hit.id for hit in hits] == [id_1.hex, id_2.hex]
    assert [hit.score for hit in hits] == [0.0, 1.0]
    assert all(hit.tenant_id == _TENANT for hit in hits)
    assert all(isinstance(hit, VectorHit) for hit in hits)


def test_search_sin_tenant_es_validation_error_sin_consulta() -> None:
    """Buscar sin comercio no emite sentencia alguna (regla 1 del slice)."""
    cursor = _CursorFalso()
    with pytest.raises(ValidationError):
        _store(_ConexionFalsa(cursor)).search(vector=[1.0], tenant_id="")
    assert cursor.ejecuciones == []


def test_search_con_vector_vacio_es_validation_error() -> None:
    """Un vector vacío no genera consulta (pgvector no admite `[]`)."""
    cursor = _CursorFalso()
    with pytest.raises(ValidationError):
        _store(_ConexionFalsa(cursor)).search(vector=[], tenant_id=_TENANT)
    assert cursor.ejecuciones == []


def test_delete_borra_solo_del_tenant_con_uuids() -> None:
    """`DELETE` con `tenant_id` + `ANY(uuid[])`; los ids viajan como uuid."""
    cursor = _CursorFalso()
    ids = [uuid4().hex, uuid4().hex]
    _store(_ConexionFalsa(cursor)).delete(tenant_id=_TENANT, ids=ids)

    sql, params = cursor.ejecuciones[0]
    assert "WHERE tenant_id = %s" in sql
    assert "chunk_id = ANY" in sql
    assert params[0] == _TENANT
    assert params[1] == [UUID(identificador) for identificador in ids]


def test_delete_sin_ids_no_consulta() -> None:
    """Lista vacía = nada que borrar y cero sentencias."""
    cursor = _CursorFalso()
    _store(_ConexionFalsa(cursor)).delete(tenant_id=_TENANT, ids=[])
    assert cursor.ejecuciones == []


def test_delete_sin_tenant_es_validation_error() -> None:
    """Borrar sin comercio no toca la base."""
    cursor = _CursorFalso()
    with pytest.raises(ValidationError):
        _store(_ConexionFalsa(cursor)).delete(tenant_id="", ids=[uuid4().hex])
    assert cursor.ejecuciones == []


def test_fallo_de_postgres_se_traduce_a_tool_error() -> None:
    """`psycopg.Error` jamás se fuga: sale como `ToolError` y cierra la conexión."""
    cursor = _CursorFalso(error=psycopg.OperationalError("sin conexion"))
    conexion = _ConexionFalsa(cursor)
    with pytest.raises(ToolError):
        _store(conexion).delete(tenant_id=_TENANT, ids=[uuid4().hex])
    assert conexion.cerrada
