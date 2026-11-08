"""Entidades del perfil de comercio y de sus prompts editables (Fase A de la consola).

El perfil reúne lo que la consola puede cambiar sin tocar código: nombre visible, tono,
idioma, bots activos, modelo y overrides de prompt. En la Fase A estos datos viven en
un JSON local; en la Fase B el contenido de los prompts pasará a Bedrock Prompt
Management y el pin de versión activa a DynamoDB.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts import AgentName

PromptKind = Literal["supervisor", "appointments", "orders", "faq"]
"""Prompts base que la consola puede editar en la Fase A."""

PROMPT_KINDS: tuple[PromptKind, ...] = ("supervisor", "appointments", "orders", "faq")
"""Orden estable para listar los prompts en la API y en la interfaz."""

DEFAULT_TENANT_ID = "Sede_Elite_01"
"""Comercio sintético con el que se siembra la consola local."""

_BOTS_POR_DEFECTO: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})


class TenantProfile(BaseModel):
    """Configuración editable de un comercio (perfil + overrides de prompt).

    Args:
        tenant_id: Identificador del comercio (`store_id` del legacy).
        display_name: Nombre comercial que usan el saludo y la interfaz.
        tone: Tono deseado para las respuestas (texto libre y orientativo).
        language: Código de idioma (p. ej. `es`).
        allowed_bots: Bots de negocio habilitados; el supervisor y FAQ no dependen de
            este conjunto (regla del slice `supervisor`).
        model_id: Modelo de Bedrock opcional; `None` usa el del entorno.
        prompts: Overrides por tipo de prompt; si falta uno, se usa
            `prompts/base/<kind>.md`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    tenant_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    tone: str = Field(default="cercano", min_length=1, max_length=120)
    language: str = Field(default="es", min_length=2, max_length=10)
    allowed_bots: frozenset[AgentName] = Field(default_factory=lambda: _BOTS_POR_DEFECTO)
    model_id: str | None = Field(default=None, max_length=200)
    prompts: dict[PromptKind, str] = Field(default_factory=dict)


class TenantProfileUpdate(BaseModel):
    """Campos opcionales que la consola puede cambiar de un perfil.

    Se usa `model_dump(exclude_unset=True)` para distinguir «no enviado» de «enviado
    como `None`» (p. ej. limpiar `model_id`). El `tenant_id` no se cambia nunca.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    tone: str | None = Field(default=None, min_length=1, max_length=120)
    language: str | None = Field(default=None, min_length=2, max_length=10)
    allowed_bots: frozenset[AgentName] | None = None
    model_id: str | None = Field(default=None, max_length=200)


def default_profile(tenant_id: str = DEFAULT_TENANT_ID) -> TenantProfile:
    """Construye el perfil sintético con el que arranca la consola local.

    Args:
        tenant_id: Comercio a sembrar.

    Returns:
        Perfil con nombre legible, tono cercano y todos los bots de negocio activos.
    """
    return TenantProfile(
        tenant_id=tenant_id,
        display_name="Sede Elite",
        tone="cercano",
        language="es",
        allowed_bots=_BOTS_POR_DEFECTO,
        model_id=None,
        prompts={},
    )
