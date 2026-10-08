"""Almacenamiento vectorial tras un port (Paso 1; primer uso en el RAG, Paso 7).

`knowledge_rag`, `appointments` y `orders` buscan conocimiento (chunks, horarios,
catálogo) sin saber que debajo hay Aurora+pgvector: solo ven este `Protocol`. El
embedding de la consulta se calcula **fuera** de este port (Paso 7), que recibe el
vector ya calculado y devuelve los vecinos más cercanos **siempre filtrados por
`tenant_id`**.

Los tipos imitan lo que devuelve una búsqueda por similitud sin nombrar columnas ni
índices concretos de PostgreSQL: la traducción vive en `adapters/aurora`.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class VectorRecord(BaseModel):
    """Texto vectorizado listo para indexar, con su identidad de negocio.

    Args:
        id: Identificador estable del registro dentro del comercio.
        tenant_id: Comercio dueño del registro; el adapter lo guarda en la fila para
            filtrar siempre por él (ninguna búsqueda cruza comercios).
        text: Texto original del chunk; se devuelve tal cual en los resultados.
        vector: Embedding normalizado, ya calculado por el llamador.
        metadata: Datos auxiliares (p. ej. sección, categoría) para filtros o citas.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    vector: list[float] = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class VectorHit(BaseModel):
    """Vecino devuelto por una búsqueda por similitud.

    Args:
        id: Identificador del registro encontrado.
        tenant_id: Comercio al que pertenece (siempre el mismo que el de la búsqueda).
        text: Texto original del registro encontrado.
        score: Similitud reportada por el almacén; el adapter la normaliza a 0..1
            cuando el motor devuelve distancias.
        metadata: Metadatos del registro, para citar la fuente en la respuesta.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class VectorStorePort(Protocol):
    """Búsqueda de registros por similitud vectorial, aislada por tenant."""

    def upsert(self, *, records: Sequence[VectorRecord]) -> None:
        """Indexa o actualiza registros (idempotente por `(tenant_id, id)`).

        Args:
            records: Registros con su embedding ya calculado.

        Raises:
            ToolError: Si el almacén rechaza la escritura (lo traduce el adapter).
        """
        ...

    def search(
        self,
        *,
        vector: Sequence[float],
        tenant_id: str,
        limit: int = 5,
    ) -> Sequence[VectorHit]:
        """Devuelve los `limit` registros más parecidos **del tenant indicado**.

        Args:
            vector: Embedding de la consulta, con la misma dimensión que los indexados.
            tenant_id: Comercio cuyo conocimiento se consulta; jamás se infiere del
                payload del LLM (MULTI_TENANCY §5).
            limit: Máximo de resultados; el adapter lo recorta a un máximo seguro.

        Returns:
            Vecinos ordenados de más a menos similar; vacío si no hay coincidencias.

        Raises:
            ToolError: Si la búsqueda falla (lo traduce el adapter).
        """
        ...

    def delete(self, *, tenant_id: str, ids: Sequence[str]) -> None:
        """Borra registros del tenant indicado (purga o reindexado).

        Args:
            tenant_id: Comercio dueño de los registros a borrar.
            ids: Identificadores a eliminar; ignorar cualquier id ajeno al tenant.

        Raises:
            ToolError: Si el borrado falla (lo traduce el adapter).
        """
        ...
