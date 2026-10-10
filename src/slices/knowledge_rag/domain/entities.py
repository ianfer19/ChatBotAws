"""Entidades de conocimiento del slice (Paso 7).

Un `SourceDocument` es la unidad de ingesta (catálogo, FAQ o política de un
tenant) tal y como llega de la fuente; `chunk_document` lo trocea en
`ContentChunk` antes de embeber. Inmutables y sin campos extra: lo que no se
valida no se indexa.
"""

from pydantic import BaseModel, ConfigDict, Field


class _KnowledgeBase(BaseModel):
    """Base común de las entidades de este slice: inmutable y sin campos extra."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceDocument(_KnowledgeBase):
    """Documento de conocimiento de un comercio, listo para ingerir.

    Args:
        tenant_id: Comercio dueño del documento; obligatorio y no vacío
            (ningún documento se indexa sin tenant asignado).
        source_type: Origen **crudo** (`product`, `service`, `faq`, `policy`);
            la regla `validate_document` lo contrasta con la allowlist
            (anti-poisoning) porque llega desde una fuente externa.
        source_id: Id de la fuente en el backend legacy (para purgar y citar).
        title: Título de la fuente, si la tiene.
        content: Texto completo a trocear (no puede ser solo espacios).
        metadata: Metadatos auxiliares de la fuente (sección, categoría…).
    """

    tenant_id: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=32)
    source_id: str = Field(min_length=1, max_length=128)
    title: str | None = None
    content: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class ContentChunk(_KnowledgeBase):
    """Fragmento de un `SourceDocument` tras el chunking, antes de embeber.

    Args:
        tenant_id: Comercio dueño; se hereda del documento y jamás cambia.
        source_type: Origen validado de la fuente (allowlist de `rules`).
        source_id: Id de la fuente de la que procede el fragmento.
        title: Título de la fuente, si la tiene.
        text: Texto del fragmento (ya recortado al tamaño máximo).
        position: Posición del fragmento dentro del documento (orden de ingesta).
        metadata: Metadatos heredados del documento fuente.
    """

    tenant_id: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=32)
    source_id: str = Field(min_length=1, max_length=128)
    title: str | None = None
    text: str = Field(min_length=1)
    position: int = Field(ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)
