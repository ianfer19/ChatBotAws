"""Errores tipados del dominio de citas: los nodos y tools los traducen a respuesta.

Subclases de `shared.errors.AppError` con `code` estable para logs, métricas y tests;
el mensaje es para el log, nunca se muestra tal cual al usuario final.

`TODO(decision)`: `SlotUnavailable`, `OutsideOpeningHours` y `LegacyTimeout` se añaden en
el Paso 5, cuando lleguen las reglas de solape/horario y el adapter del backend legacy.
"""

from shared.errors import AppError


class IncompleteAppointmentData(AppError):
    """Faltan los datos mínimos (fecha, hora, nombre o contacto): no se crea nada."""

    code = "incomplete_appointment_data"
    http_status = 400


class TenantMismatch(AppError):
    """La cita no existe en este comercio: rechazo genérico, sin detalles (regla 1)."""

    code = "tenant_mismatch"
    http_status = 403
