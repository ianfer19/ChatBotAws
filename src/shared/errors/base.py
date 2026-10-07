"""Excepciones tipadas con código estable: los handlers las traducen a respuestas.

Nunca se expone un stack trace ni el texto completo de `details` al usuario final; el
código (`code`) es el contrato estable para logs, métricas y pruebas.
"""

from typing import ClassVar


class AppError(Exception):
    """Base de todos los errores tipados del sistema.

    Cada subclase fija un `code` estable y un `http_status` que los handlers usan como
    pista para traducir la respuesta (el handler decide el cuerpo final).

    Args:
        message: Descripción en español para logs; no se muestra tal cual al usuario.
        details: Pares clave-valor adicionales para el log. Prohibido PII completa,
            tokens o credenciales aquí (se loguean tal cual).

    Example:
        >>> raise AppError("fallo genérico", details={"origen": "handler"})
        Traceback (most recent call last):
        ...
        shared.errors.base.AppError: fallo genérico
    """

    code: ClassVar[str] = "app_error"
    http_status: ClassVar[int] = 500

    def __init__(self, message: str, *, details: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details if details is not None else {}

    def to_dict(self) -> dict[str, object]:
        """Representación segura para log o respuesta: código, mensaje y detalles.

        Returns:
            dict con `error` (código estable), `message` y `details`; sin trazas.
        """
        return {"error": self.code, "message": self.message, "details": self.details}


class ValidationError(AppError):
    """Datos de entrada inválidos (payload, contrato o validación de dominio).

    No confundir con `pydantic.ValidationError`, que capturan los handlers al validar
    contratos; este es el error de aplicación que se lanza desde el código.
    """

    code = "validation_error"
    http_status = 400


class TenantError(AppError):
    """Problema relacionado con el comercio (tenant) resuelto en el gateway."""

    code = "tenant_error"
    http_status = 403


class TenantNotFoundError(TenantError):
    """No existe mapeo de canal→tenant; responde «comercio no disponible» (D5)."""

    code = "tenant_not_found"
    http_status = 404


class ContextNotSetError(AppError):
    """El handler no fijó el `TenantContext` antes de usarlo (bug de composición)."""

    code = "context_not_set"
    http_status = 500


class ToolError(AppError):
    """La tool falló contra el backend o un servicio externo (timeout, 5xx, red)."""

    code = "tool_error"
    http_status = 502


class ToolTimeoutError(ToolError):
    """La tool excedió su timeout y se abandonó el intento."""

    code = "tool_timeout"
    http_status = 504
