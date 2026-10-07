"""Errores tipados del sistema (dominio, tools, tenant) y excepciones base con código estable.

Los errores específicos de un slice se declaran en el slice subclasificando `AppError`
(p. ej. `InvalidSignatureError` en `conversation_gateway`).
"""

from shared.errors.base import (
    AppError,
    ContextNotSetError,
    TenantError,
    TenantNotFoundError,
    ToolError,
    ToolTimeoutError,
    ValidationError,
)

__all__ = [
    "AppError",
    "ContextNotSetError",
    "TenantError",
    "TenantNotFoundError",
    "ToolError",
    "ToolTimeoutError",
    "ValidationError",
]
