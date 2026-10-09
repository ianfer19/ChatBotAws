"""Errores tipados del dominio del supervisor: los nodos los traducen a respuesta.

Subclases de `shared.errors.AppError` con `code` estable para logs, métricas y tests;
el mensaje es para el log, nunca se muestra tal cual al usuario final (los nodos de
`application/` construyen la respuesta amable con una plantilla propia).
"""

from shared.errors import AppError, TenantError


class AmbiguousIntentError(AppError):
    """Confianza por debajo del umbral o salida ilegible: ruta segura, nunca inventar."""

    code = "ambiguous_intent"
    http_status = 422


class IntentNotAllowedByTenant(TenantError):
    """Intención válida pero fuera de los `allowed_bots` del comercio (MULTI_TENANCY)."""

    code = "intent_not_allowed"
    http_status = 403


class MissingTurnInputsError(AppError):
    """El turno llegó sin los insumos obligatorios: sin historial o sin contexto (7.2)."""

    code = "missing_turn_inputs"
    http_status = 400
