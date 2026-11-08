"""Modelos de entrada/salida de la consola para perfiles y prompts (sin framework)."""

from pydantic import BaseModel, ConfigDict, Field

from slices.tenant_prompts.domain.entities import PromptKind


class PromptInfo(BaseModel):
    """Resumen de un prompt para listarlo en la interfaz.

    Args:
        kind: Tipo de prompt.
        is_override: `True` si el comercio tiene contenido propio; `False` si usa la base.
        length: Longitud del contenido efectivo (override o base).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: PromptKind
    is_override: bool
    length: int = Field(ge=0)


class PromptView(BaseModel):
    """Contenido efectivo de un prompt con su origen.

    Args:
        kind: Tipo de prompt.
        content: Texto que se usará en el siguiente turno.
        is_override: `True` si viene del JSON del comercio; `False` si es la base.
        base_content: Plantilla base de `prompts/base/`, para poder restaurarla.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: PromptKind
    content: str
    is_override: bool
    base_content: str
