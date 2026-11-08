"""Capa application del slice tenant_prompts. Casos de uso de perfil y prompts."""

from slices.tenant_prompts.application.models import PromptInfo, PromptView
from slices.tenant_prompts.application.service import TenantConfigService

__all__ = ["PromptInfo", "PromptView", "TenantConfigService"]
