"""Errores tipados del dominio de citas: los nodos y tools los traducen a respuesta.

Subclases de `shared.errors.AppError` con `code` estable para logs, métricas y tests;
el mensaje es para el log, nunca se muestra tal cual al usuario final.

`TODO(decision)`: `LegacyTimeout` llega con el adapter del backend legacy (Paso 11),
cuando exista la llamada HTTP real con timeout.
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


class SlotUnavailable(AppError):
    """El turno pedido está ocupado o ya pasó: no se propone nada (regla 2)."""

    code = "slot_unavailable"
    http_status = 409


class OutsideOpeningHours(AppError):
    """La fecha/hora cae fuera del horario de atención del comercio (regla 3)."""

    code = "outside_opening_hours"
    http_status = 422


class DraftNotFound(AppError):
    """No hay ningún draft con ese identificador en este comercio."""

    code = "draft_not_found"
    http_status = 404


class DraftNotCommittable(AppError):
    """El draft no está en un estado que admita la transición pedida (ADR 0011)."""

    code = "draft_not_committable"
    http_status = 409
