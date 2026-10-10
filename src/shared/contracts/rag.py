"""Contratos de conocimiento (RAG) entre `knowledge_rag` y sus consumidores (Paso 7).

El especialista `faq` y las tools de otros slices reciben evidencia ya recuperada y
filtrada por tenant. La consulta **no admite `tenant_id`**: se inyecta del contexto
resuelto en el gateway (MULTI_TENANCY §5), nunca del payload del LLM.

Contrato versionado (`schema_version`), inmutable y sin campos extra: lo que no pasa
el contrato no se indexa ni se usa para fundamentar una respuesta.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["product", "service", "faq", "policy"]
"""Origen permitido de un chunk (DATA_MODEL); la lista se contrasta también en la
ingesta y en la recuperación (anti-poisoning, `knowledge_rag/domain/rules.py`)."""


class _RagBase(BaseModel):
    """Base común de este módulo: inmutable y sin campos extra."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class KnowledgeQuery(_RagBase):
    """Consulta de conocimiento lista para recuperar evidencia.

    Args:
        query: Texto a buscar (la pregunta del cliente, sin PII).
        top_k: Máximo de candidatos a recuperar antes del umbral (4-8,
            `TODO(verify)` al calibrar con los evals).
    """

    schema_version: Literal[1] = 1
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class EvidenceChunk(_RagBase):
    """Fragmento de conocimiento recuperado: la evidencia con la que se responde.

    La respuesta se construye **solo** con estos chunks (`grounding_source`,
    ADR 0008); nada fuera de este contrato fundamenta una respuesta.

    Args:
        chunk_id: Identificador estable del fragmento dentro del comercio.
        text: Texto del fragmento, tal cual se indexó.
        score: Similitud 0..1 ya normalizada por el almacén.
        source_type: Origen permitido de la fuente.
        source_id: Id de la fuente en el backend legacy (para citar y purgar).
        title: Título de la fuente, si la tiene (cita corta en la respuesta).
        metadata: Metadatos de la fuente (sección, categoría…).
    """

    schema_version: Literal[1] = 1
    chunk_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    source_type: SourceType
    source_id: str = Field(min_length=1, max_length=128)
    title: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
