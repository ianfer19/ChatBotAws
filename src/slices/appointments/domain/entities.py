"""Entidad `Appointment`: la cita tal como la conoce este sistema.

Estados canónicos (Paso 5): `confirmed` lo pone el commit del draft (ADR 0011),
`cancelled` la cancelación o el deshacer, y `pending` queda reservado para datos
heredados del backend legacy (`TODO(verify)`: mapa real de estados de `ops_service`,
ver `INTEGRATION_WITH_LEGACY.md` §4).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AppointmentStatus = Literal["pending", "confirmed", "cancelled"]
"""Estados posibles de una cita; el sistema solo crea `confirmed` y `cancelled`."""


class Appointment(BaseModel):
    """Cita reservada en un comercio, ligada a su tenant y a su turno de inicio.

    Modelo inmutable (`frozen`): una vez guardada, cambiarla es un caso de uso
    explícito que vuelve a pasar por el dominio, nunca una asignación lateral.

    Args:
        id: Identificador de la cita (generado en el commit del draft).
        tenant_id: Comercio dueño de la cita; siempre igual al del contexto resuelto.
        starts_at: Inicio de la cita (naive, hora local del comercio).
        customer_name: Nombre del cliente que reserva.
        contact: Medio de contacto (teléfono, correo o handle) del cliente.
        status: Estado canónico del módulo (`AppointmentStatus`).
        correlation_id: Idempotencia de la creación: la misma petición no duplica cita.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    customer_name: str = Field(min_length=1, max_length=120)
    contact: str = Field(min_length=1, max_length=64)
    status: AppointmentStatus = Field(description="Estado canónico (AppointmentStatus)")
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)
