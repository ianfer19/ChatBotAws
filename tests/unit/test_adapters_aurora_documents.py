"""Tests unitarios de `AuroraDocumentRegistry`: tenant, hash y traducción de errores.

Sin PostgreSQL real: dobles de conexión/cursor. El registry vive en el slice
(`slices/knowledge_rag/infrastructure/aurora.py`) porque implementa un port de
su dominio; aquí se verifica que toda sentencia lleva `tenant_id` y que ningún
`psycopg.Error` se fuga.
"""

from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection

from shared.errors import ToolError, ValidationError
from slices.knowledge_rag.domain.entities import StoredDocument
from slices.knowledge_rag.domain.ports import DocumentRegistryPort
from slices.knowledge_rag.infrastructure.aurora import AuroraDocumentRegistry

_TENANT = "Sede_Elite_01"
_SOURCE = "faq-1"


class _CursorFalso:
    """Cursor que registra `(sql, params)` y devuelve una fila fija."""

    def __init__(
        self,
        fila: tuple[Any, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Prepara la fila o el error que devolverá cada test.

        Args:
            fila: Fila que devolverá `fetchone` (o `None`).
            error: Excepción que lanzará `execute`.
        """
        self.ejecuciones: list[tuple[str, tuple[Any, ...]]] = []
        self._fila = fila
        self._error = error

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        """Registra la sentencia; lanza el error configurado si lo hay."""
        self.ejecuciones.append((query, params if params is not None else ()))
        if self._error is not None:
            raise self._error

    def fetchall(self) -> list[tuple[Any, ...]]:
        """No usado por este adapter; existe por simetría con el cursor real."""
        return []

    def fetchone(self) -> tuple[Any, ...] | None:
        """Devuelve la fila registrada, o `None` si no hay."""
        return self._fila

    def __enter__(self) -> "_CursorFalso":
        """El cursor se usa como gestor de contexto, como el de psycopg."""
        return self

    def __exit__(self, *args: object) -> None:
        """Cierra el gestor sin propagar nada."""


class _ConexionFalsa:
    """Conexión que entrega el cursor falso y registra si se cerró."""

    def __init__(self, cursor: _CursorFalso) -> None:
        """Guarda el cursor que entregará cada `cursor()`.

        Args:
            cursor: Cursor falso del test.
        """
        self._cursor = cursor
        self.cerrada = False

    def cursor(self) -> _CursorFalso:
        """Devuelve el cursor falso."""
        return self._cursor

    def close(self) -> None:
        """Marca la conexión como cerrada."""
        self.cerrada = True


def _registry(conexion: _ConexionFalsa) -> AuroraDocumentRegistry:
    """Registry con la fábrica apuntando a la conexión falsa (cast por mypy).

    Args:
        conexion: Conexión falsa del test.

    Returns:
        `AuroraDocumentRegistry` listo para usar.
    """
    return AuroraDocumentRegistry(connect=lambda: cast("Connection[tuple[Any, ...]]", conexion))


def test_es_un_document_registry_port() -> None:
    """Debe satisfacer el port del dominio (igual que su doble en memoria)."""
    registry = _registry(_ConexionFalsa(_CursorFalso()))
    assert isinstance(registry, DocumentRegistryPort)


def test_get_devuelve_hash_e_ids_normalizados_a_hex() -> None:
    """La fila sale como `StoredDocument` con los ids en el formato de la ingesta."""
    ids = [uuid4(), uuid4()]
    cursor = _CursorFalso(fila=("abc123", [str(identificador) for identificador in ids]))
    registro = _registry(_ConexionFalsa(cursor)).get_document(tenant_id=_TENANT, source_id=_SOURCE)

    sql, params = cursor.ejecuciones[0]
    assert "WHERE d.tenant_id = %s" in sql
    assert "knowledge_chunks" in sql
    assert params == (_TENANT, _SOURCE)
    assert registro is not None
    assert registro.content_hash == "abc123"
    assert registro.chunk_ids == (ids[0].hex, ids[1].hex)


def test_get_sin_fila_devuelve_none() -> None:
    """Fuente nunca ingerida = `None` (la ingesta la tratará como nueva)."""
    cursor = _CursorFalso(fila=None)
    registro = _registry(_ConexionFalsa(cursor)).get_document(tenant_id=_TENANT, source_id=_SOURCE)
    assert registro is None


def test_get_sin_tenant_o_fuente_es_validation_error_sin_consulta() -> None:
    """Ninguna lectura se emite sin saber de quién es el documento."""
    cursor = _CursorFalso()
    with pytest.raises(ValidationError):
        _registry(_ConexionFalsa(cursor)).get_document(tenant_id="", source_id=_SOURCE)
    with pytest.raises(ValidationError):
        _registry(_ConexionFalsa(cursor)).get_document(tenant_id=_TENANT, source_id="")
    assert cursor.ejecuciones == []


def test_get_con_fila_ilegal_es_tool_error() -> None:
    """Una fila con forma rara no se fuga como `ValueError`/`IndexError`."""
    cursor = _CursorFalso(fila=("hash", "no-es-lista"))
    with pytest.raises(ToolError):
        _registry(_ConexionFalsa(cursor)).get_document(tenant_id=_TENANT, source_id=_SOURCE)


def test_get_con_id_no_uuid_es_tool_error() -> None:
    """Un chunk id que no es uuid no puede normalizarse: `ToolError` tipado."""
    cursor = _CursorFalso(fila=("hash", ["no-soy-uuid"]))
    with pytest.raises(ToolError):
        _registry(_ConexionFalsa(cursor)).get_document(tenant_id=_TENANT, source_id=_SOURCE)


def test_get_fallo_de_postgres_es_tool_error_y_cierra() -> None:
    """`psycopg.Error` se traduce y la conexión se cierra igualmente."""
    cursor = _CursorFalso(error=psycopg.OperationalError("sin conexion"))
    conexion = _ConexionFalsa(cursor)
    with pytest.raises(ToolError):
        _registry(conexion).get_document(tenant_id=_TENANT, source_id=_SOURCE)
    assert conexion.cerrada


def test_save_hace_upsert_con_tenant_y_hash() -> None:
    """El `INSERT ... ON CONFLICT` lleva tenant, fuente y el hash de la corrida."""
    cursor = _CursorFalso()
    conexion = _ConexionFalsa(cursor)
    documento = StoredDocument(content_hash="sha-256", chunk_ids=("a1",))

    _registry(conexion).save_document(tenant_id=_TENANT, source_id=_SOURCE, document=documento)

    sql, params = cursor.ejecuciones[0]
    assert "documents" in sql
    assert "ON CONFLICT" in sql
    assert params == (_TENANT, _SOURCE, "sha-256")
    assert conexion.cerrada


def test_save_sin_tenant_es_validation_error_sin_consulta() -> None:
    """Nada se escribe sin comercio."""
    cursor = _CursorFalso()
    with pytest.raises(ValidationError):
        _registry(_ConexionFalsa(cursor)).save_document(
            tenant_id="", source_id=_SOURCE, document=StoredDocument(content_hash="x")
        )
    assert cursor.ejecuciones == []


def test_save_fallo_de_postgres_es_tool_error_y_cierra() -> None:
    """El error de la escritura también sale tipado y con la conexión cerrada."""
    cursor = _CursorFalso(error=psycopg.OperationalError("sin conexion"))
    conexion = _ConexionFalsa(cursor)
    with pytest.raises(ToolError):
        _registry(conexion).save_document(
            tenant_id=_TENANT, source_id=_SOURCE, document=StoredDocument(content_hash="x")
        )
    assert conexion.cerrada
