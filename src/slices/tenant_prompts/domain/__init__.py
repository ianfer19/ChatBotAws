"""Capa domain del slice tenant_prompts. Modelos, reglas de negocio y ports propios."""

from .entities import (
    DEFAULT_TENANT_ID,
    PROMPT_KINDS,
    PromptKind,
    TenantProfile,
    TenantProfileUpdate,
    default_profile,
)
from .ports import TenantProfileRepositoryPort

__all__ = [
    "DEFAULT_TENANT_ID",
    "PROMPT_KINDS",
    "PromptKind",
    "TenantProfile",
    "TenantProfileRepositoryPort",
    "TenantProfileUpdate",
    "default_profile",
]
