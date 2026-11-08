"""Errores propios del slice `tenant_prompts` (códigos estables para la API)."""

from shared.errors import AppError


class TenantProfileNotFoundError(AppError):
    """No existe perfil para el comercio pedido (404 en la consola)."""

    code = "tenant_profile_not_found"
    http_status = 404


class PromptOverrideInvalidError(AppError):
    """El contenido del prompt no cumple las reglas mínimas (vacío o demasiado largo)."""

    code = "prompt_override_invalid"
    http_status = 400
