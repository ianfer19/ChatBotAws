"""Entidad `Appointment`: la cita tal como la conoce este sistema.

Contrato previo del Paso 1: aquí solo viven los campos necesarios para tipar los
puertos y los dobles; las reglas de negocio (solapes, horario de atención,
confirmación) llegan con el Paso 5 y pueden añadir campos o invariantes.

`TODO(decision)`: los estados canónicos de la cita (y por tanto el tipo de `status`)
se fijan en el Paso 5, cuando se lea el contrato real de `ops_service`
(`catalogo_endpoints.md`); mientras tanto el estado es texto crudo del legacy.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Appointment(BaseModel):
    """Cita reservada en un comercio, ligada a su tenant y a su turno de inicio.

    Modelo inmutable (`frozen`): una vez guardada, cambiarla es un caso de uso
    explícito que vuelve a pasar por el dominio, nunca una asignación lateral.

    Args:
        id: Identificador de la cita devuelto por el backend.
        tenant_id: Comercio dueño de la cita; siempre igual al del contexto resuelto.
        starts_at: Inicio de la cita (con zona horaria).
        customer_name: Nombre del cliente que reserva.
        contact: Medio de contacto (teléfono, correo o handle) del cliente.
        status: Estado crudo reportado por el legacy (ver `TODO(decision)` del módulo).
        correlation_id: Idempotencia de la creación: la misma petición no duplica cita.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    customer_name: str = Field(min_length=1, max_length=120)
    contact: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)
