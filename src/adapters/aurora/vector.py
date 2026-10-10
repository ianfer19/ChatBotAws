"""Adapter de Aurora PostgreSQL + pgvector: `VectorStorePort` (Paso 7: RAG).

Implementa el almacén vectorial del conocimiento sobre la tabla
`knowledge_chunks` de DATA_MODEL. Invariantes que este adapter garantiza:

- **Toda** sentencia lleva `tenant_id` explícito (no hay consulta sin comercio:
  cláusula obligatoria en MULTI_TENANCY; una query sin ella es un bug de fuga).
- Los ids del port son strings (uuid5 hex de la ingesta) y la columna `chunk_id`
  es `uuid`: se convierte en los dos sentidos y siempre se normaliza a `.hex`
  para que la ingesta y el registro vean el mismo id que escribieron.
- El score es la similitud coseno recortada a 0..1, igual que el doble en
  memoria, para que `select_evidence` no dependa de qué backend respondió.

`TODO(verify)`: Row-Level Security como segunda barrera, `statement_timeout` y
HNSW frente a IVFFlat según volumen (DATA_MODEL).
"""

import json
from collections.abc import Callable, Sequence
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg import Connection

from shared.errors import ToolError, ValidationError
from shared.logging import get_logger
from shared.ports import VectorHit, VectorRecord

_logger = get_logger(__name__)

_UPSERT_SQL = """
    INSERT INTO knowledge_chunks
        (tenant_id, chunk_id, source_type, source_id, title, content, embedding, metadata)
    VALUES (%s, %s::uuid, %s, %s, %s, %s, %s::vector, %s::jsonb)
    ON CONFLICT (tenant_id, chunk_id) DO UPDATE SET
        source_type = EXCLUDED.source_type,
        source_id   = EXCLUDED.source_id,
        title       = EXCLUDED.title,
        content     = EXCLUDED.content,
        embedding   = EXCLUDED.embedding,
        metadata    = EXCLUDED.metadata,
        ingested_at = now()
"""

_SEARCH_SQL = """
    SELECT tenant_id, chunk_id::text, content, metadata,
           (1 - (embedding <=> %s::vector)) AS score
    FROM knowledge_chunks
    WHERE tenant_id = %s
    ORDER BY embedding <=> %s::vector
    LIMIT %s
"""

_DELETE_SQL = """
    DELETE FROM knowledge_chunks
    WHERE tenant_id = %s AND chunk_id = ANY(%s::uuid[])
"""


class AuroraVectorStore:
    """`VectorStorePort` sobre `knowledge_chunks` (Aurora + pgvector).

    Abre una conexión por operación con la fábrica inyectada y la cierra
    siempre; los errores de PostgreSQL se traducen a `ToolError` (nunca se fuga
    `psycopg.Error`). Un test de contrato comprueba que es un `VectorStorePort`.
    """

    def __init__(self, *, connect: Callable[[], Connection[tuple[Any, ...]]]) -> None:
        """Guarda la fábrica de conexiones (la real o un doble de test).

        Args:
            connect: Callable que abre una conexión nueva por operación.
        """
        self._connect = connect

    def upsert(self, *, records: Sequence[VectorRecord]) -> None:
        """Indexa o reemplaza registros del mismo tenant (idempotente por id).

        Args:
            records: Registros con su embedding ya calculado; vacío no hace nada.

        Raises:
            ValidationError: Si falta tenant o el id no es un uuid.
            ToolError: Si PostgreSQL rechaza la escritura.
        """
        if not records:
            return
        for record in records:
            if not record.tenant_id:
                raise ValidationError("registro vectorial sin tenant_id")
            _as_uuid(record.id)

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for record in records:
                    cursor.execute(_UPSERT_SQL, _upsert_params(record))
        except psycopg.Error as exc:
            _logger.error(
                "aurora.vector.upsert.error",
                extra={"tenant_id": records[0].tenant_id, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudieron escribir los chunks en Aurora",
                details={"error": type(exc).__name__},
            ) from exc
        finally:
            connection.close()
        _logger.info(
            "aurora.vector.upsert.ok",
            extra={"tenant_id": records[0].tenant_id, "records": len(records)},
        )

    def search(
        self, *, vector: Sequence[float], tenant_id: str, limit: int = 5
    ) -> Sequence[VectorHit]:
        """Vecinos más parecidos **solo del tenant pedido**, por similitud coseno.

        Args:
            vector: Embedding de la consulta.
            tenant_id: Comercio cuyo conocimiento se consulta; obligatorio.
            limit: Máximo de resultados (recortado a los primeros ordenados).

        Returns:
            Hits con score en 0..1, de mayor a menor similitud.

        Raises:
            ValidationError: Si `tenant_id` está vacío.
            ToolError: Si PostgreSQL falla o la fila tiene una forma inesperada.
        """
        if not tenant_id:
            raise ValidationError("búsqueda vectorial sin tenant_id")
        literal = _vector_literal(vector)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(_SEARCH_SQL, (literal, tenant_id, literal, limit))
                filas = cursor.fetchall()
        except psycopg.Error as exc:
            _logger.error(
                "aurora.vector.search.error",
                extra={"tenant_id": tenant_id, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudo consultar Aurora",
                details={"error": type(exc).__name__},
            ) from exc
        finally:
            connection.close()
        hits = [_to_hit(fila) for fila in filas]
        _logger.info(
            "aurora.vector.search.ok",
            extra={"tenant_id": tenant_id, "results": len(hits), "limit": limit},
        )
        return hits

    def delete(self, *, tenant_id: str, ids: Sequence[str]) -> None:
        """Borra registros del tenant indicado; los ids ajenos se ignoran.

        Args:
            tenant_id: Comercio dueño de los registros.
            ids: Identificadores a eliminar; vacío no consulta.

        Raises:
            ValidationError: Si falta tenant o un id no es un uuid.
            ToolError: Si PostgreSQL rechaza el borrado.
        """
        if not tenant_id:
            raise ValidationError("borrado vectorial sin tenant_id")
        if not ids:
            return
        uuids = [_as_uuid(identificador) for identificador in ids]
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(_DELETE_SQL, (tenant_id, uuids))
        except psycopg.Error as exc:
            _logger.error(
                "aurora.vector.delete.error",
                extra={"tenant_id": tenant_id, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudieron borrar los chunks en Aurora",
                details={"error": type(exc).__name__},
            ) from exc
        finally:
            connection.close()
        _logger.info(
            "aurora.vector.delete.ok",
            extra={"tenant_id": tenant_id, "records": len(ids)},
        )


def _upsert_params(record: VectorRecord) -> tuple[object, ...]:
    """Parámetros de un `INSERT ... ON CONFLICT` (siempre con el tenant primero).

    Args:
        record: Registro a escribir.

    Returns:
        Tupla alineada con `_UPSERT_SQL`: tenant, uuid, origen, fuente, título,
        contenido, literal del vector y metadata en JSON.
    """
    metadata = record.metadata
    return (
        record.tenant_id,
        str(_as_uuid(record.id)),
        metadata.get("source_type", ""),
        metadata.get("source_id", record.id),
        metadata.get("title"),
        record.text,
        _vector_literal(record.vector),
        json.dumps(metadata, ensure_ascii=False),
    )


def _to_hit(fila: Sequence[object]) -> VectorHit:
    """Convierte una fila de `knowledge_chunks` en `VectorHit` del port.

    Args:
        fila: `(tenant_id, chunk_id::text, content, metadata, score)` de
            `_SEARCH_SQL`.

    Returns:
        Hit con id normalizado a hex y score recortado a 0..1.

    Raises:
        ToolError: Si la fila no tiene la forma esperada (no se fuga `IndexError`).
    """
    try:
        tenant_id, chunk_id, content, metadata, score = fila
        return VectorHit(
            id=_as_uuid(str(chunk_id)).hex,
            tenant_id=str(tenant_id),
            text=str(content),
            score=max(0.0, min(1.0, cast(float, score))),
            metadata=cast(dict[str, str], metadata),
        )
    except (TypeError, ValueError) as exc:
        raise ToolError("fila de knowledge_chunks con forma inesperada") from exc


def _as_uuid(identificador: str) -> UUID:
    """Valida y convierte un id del port a `uuid` (columna `chunk_id`).

    Args:
        identificador: Id string (hex uuid5 de la ingesta o su forma con guiones).

    Returns:
        El `UUID` equivalente.

    Raises:
        ValidationError: Si el id no es un uuid válido.
    """
    try:
        return UUID(identificador)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(
            "id de chunk no es un uuid",
            details={"id": identificador},
        ) from exc


def _vector_literal(vector: Sequence[float]) -> str:
    """Literal pgvector de un embedding (texto `[1.0, 2.0, ...]`).

    Args:
        vector: Embedding a serializar.

    Returns:
        Literal aceptado por la columna `vector(...)` de pgvector.

    Raises:
        ValidationError: Si el vector está vacío (pgvector no admite vectores vacíos).
    """
    if not vector:
        raise ValidationError("vector vacío: nada que buscar ni escribir")
    return json.dumps([float(valor) for valor in vector])
