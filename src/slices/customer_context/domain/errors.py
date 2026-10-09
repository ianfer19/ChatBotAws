"""Errores tipados del dominio de contexto de cliente (Paso 4).

Subclases de `shared.errors.AppError` con `code` estable; el mensaje es para el log,
nunca se muestra tal cual al usuario final.

`CustomerContextNotFound` **no existe deliberadamente**: un cliente nuevo (o uno sin
historial) no es un error — el caso de uso devuelve un contexto vacío por defecto
(regla de la tabla de errores del slice). Solo el TTL vencido tiene señal propia.
"""

from shared.errors import AppError


class ContextStaleError(AppError):
    """El contexto superó su TTL: el caso de uso lo traduce a contexto vacío.

    La traducción (AGENTS del slice) es: contexto vacío + relectura en el siguiente
    turno; jamás se expone al usuario.
    """

    code = "context_stale"
    http_status = 410
