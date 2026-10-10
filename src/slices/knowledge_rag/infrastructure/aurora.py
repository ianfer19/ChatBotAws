"""Adapter de la tabla `documents` sobre Aurora: `DocumentRegistryPort` (Paso 7).

Vive en la capa `infrastructure` del slice (no en `adapters/`): implementa un
port del propio dominio y los adapters transversales no pueden importar slices.
Usa la fábrica de conexiones de `adapters/aurora/connection`.

Guarda el `content_hash` por fuente que hace idempotente la re-ingesta (RAG.md)
y devuelve también los `chunk_ids` leyéndolos de `knowledge_chunks` (una sola
consulta correlacionada): los ids viven en los chunks, no se duplican en dos
sitios. Toda sentencia filtra por `tenant_id` (MULTI_TENANCY) y los errores de
PostgreSQL se traducen a `ToolError`.

`TODO(verify)`: purge por `source_type` (hoy el origen vive en el metadata de
los chunks, que es donde lo consume la citación).
"""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection

from shared.errors import ToolError, ValidationError
from shared.logging import get_logger
from slices.knowledge_rag.domain.entities import StoredDocument

_logger = get_logger(__name__)

_GET_SQL = """
    SELECT d.content_hash,
           ARRAY(
               SELECT chunk_id::text
               FROM knowledge_chunks k
               WHERE k.tenant_id = d.tenant_id AND k.source_id = d.source_id
           )
    FROM documents d
    WHERE d.tenant_id = %s AND d.source_id = %s
"""

_SAVE_SQL = """
    INSERT INTO documents (tenant_id, source_id, content_hash)
    VALUES (%s, %s, %s)
    ON CONFLICT (tenant_id, source_id) DO UPDATE SET
        content_hash = EXCLUDED.content_hash,
        ingested_at  = now()
"""


class AuroraDocumentRegistry:
    """`DocumentRegistryPort` sobre la tabla `documents` de Aurora.

    Abre una conexión por operación con la fábrica inyectada y la cierra siempre.
    """

    def __init__(self, *, connect: Callable[[], Connection[tuple[Any, ...]]]) -> None:
        """Guarda la fábrica de conexiones (la real o un doble de test).

        Args:
            connect: Callable que abre una conexión nueva por operación.
        """
        self._connect = connect

    def get_document(self, *, tenant_id: str, source_id: str) -> StoredDocument | None:
        """Recupera hash e ids de chunks de una fuente del tenant.

        Args:
            tenant_id: Comercio dueño del documento.
            source_id: Id de la fuente en el backend legacy.

        Returns:
            El registro conocido, o `None` si la fuente nunca se ingerió.

        Raises:
            ValidationError: Si falta `tenant_id` o `source_id`.
            ToolError: Si PostgreSQL falla o la fila es ilegible.
        """
        if not tenant_id or not source_id:
            raise ValidationError(
                "registro de documentos sin tenant_id o source_id",
                details={"tenant_id": tenant_id, "source_id": source_id},
            )
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(_GET_SQL, (tenant_id, source_id))
                fila = cursor.fetchone()
        except psycopg.Error as exc:
            _logger.error(
                "aurora.documents.get.error",
                extra={"tenant_id": tenant_id, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudo leer el registro de documentos",
                details={"error": type(exc).__name__},
            ) from exc
        finally:
            connection.close()
        if fila is None:
            return None
        return _to_stored(fila)

    def save_document(self, *, tenant_id: str, source_id: str, document: StoredDocument) -> None:
        """Guarda (o reemplaza) el hash de indexación de una fuente.

        Args:
            tenant_id: Comercio dueño del documento.
            source_id: Id de la fuente en el backend legacy.
            document: Hash e ids de chunks resultantes de la corrida.

        Raises:
            ValidationError: Si falta `tenant_id` o `source_id`.
            ToolError: Si PostgreSQL rechaza la escritura.
        """
        if not tenant_id or not source_id:
            raise ValidationError(
                "registro de documentos sin tenant_id o source_id",
                details={"tenant_id": tenant_id, "source_id": source_id},
            )
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(_SAVE_SQL, (tenant_id, source_id, document.content_hash))
        except psycopg.Error as exc:
            _logger.error(
                "aurora.documents.save.error",
                extra={"tenant_id": tenant_id, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudo escribir el registro de documentos",
                details={"error": type(exc).__name__},
            ) from exc
        finally:
            connection.close()
        _logger.info(
            "aurora.documents.save.ok",
            extra={"tenant_id": tenant_id, "chunks": len(document.chunk_ids)},
        )


def _to_stored(fila: Sequence[object]) -> StoredDocument:
    """Convierte la fila de `documents` en `StoredDocument` del dominio.

    Args:
        fila: `(content_hash, chunk_ids[])` de `_GET_SQL`.

    Returns:
        Registro con los ids normalizados a hex (el formato que escribió la
        ingesta y que espera el borrado de chunks).

    Raises:
        ToolError: Si la fila no tiene la forma esperada, si un id no es uuid o
            si el hash viene vacío.
    """
    try:
        content_hash, chunk_ids = fila
        if not isinstance(chunk_ids, list):
            raise TypeError("chunk_ids no es una lista")
        return StoredDocument(
            content_hash=str(content_hash),
            chunk_ids=tuple(UUID(str(identificador)).hex for identificador in chunk_ids),
        )
    except (TypeError, ValueError) as exc:
        raise ToolError("fila de documents con forma inesperada") from exc
