"""Modelos Pydantic de la aplicación: lo que el LLM propone y lo que devuelven las tools.

Viven en `application/` (decisión del Paso 3): los contratos públicos hacia otros slices
se publican en `shared/contracts/` cuando `supervisor` los necesite (Paso 4). Nada de
aquí viaja al `domain/`, que sigue sin conocer estos tipos.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ToolName = Literal[
    "get_availability",
    "create_appointment",
    "cancel_appointment",
    "get_opening_hours",
]
"""Tools que este grafo sabe ejecutar (allowlist; «LangGraph decide si puede usarla»)."""

ProposalAction = Literal[ToolName, "reply"]
"""Acción propuesta por el LLM: una tool o `reply` (sin herramienta)."""


class AppointmentProposal(BaseModel):
    """Conclusión de `understand` sobre el turno, ya validada contra el esquema.

    El modelo es `extra="forbid"`: si el LLM añade campos ajenos (p. ej. `tenant_id`),
    el parseo falla y el turno cae a la ruta de aclaración — el aislamiento por tenant
    no puede depender de lo que el modelo escriba.

    Args:
        action: Tool a ejecutar o `reply` si no hay nada que ejecutar.
        date: Fecha propuesta en ISO (`YYYY-MM-DD`).
        time: Hora propuesta (`HH:MM`).
        customer_name: Nombre del cliente.
        contact: Medio de contacto del cliente.
        appointment_id: Cita a cancelar.
        party_size: Número de personas (consulta de disponibilidad).
        reply: Pista de texto cuando `action="reply"` (saludo, aclaración).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ProposalAction
    date: str | None = Field(default=None, max_length=10)
    time: str | None = Field(default=None, max_length=5)
    customer_name: str | None = Field(default=None, max_length=120)
    contact: str | None = Field(default=None, max_length=64)
    appointment_id: str | None = Field(default=None, max_length=64)
    party_size: int | None = Field(default=None, ge=1)
    reply: str | None = Field(default=None, max_length=500)


class Slot(BaseModel):
    """Hueco de disponibilidad ofrecido por la tool (nunca inventado por el LLM)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime
    end: datetime


class AppointmentView(BaseModel):
    """Vista de una cita para redactar la respuesta (sin datos internos de más)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    customer_name: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=32)


class OpeningHoursDay(BaseModel):
    """Horario de atención de un día de la semana, en hora local del comercio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weekday: int = Field(ge=0, le=6, description="0 = lunes .. 6 = domingo")
    open_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    close_time: str = Field(pattern=r"^\d{2}:\d{2}$")


class ToolResult(BaseModel):
    """Salida de una tool del grafo: la única fuente de datos de la respuesta.

    Args:
        tool: Tool que produjo el resultado (debe coincidir con la pedida).
        slots: Huecos libres (`get_availability`).
        appointment: Cita creada (`create_appointment`).
        hours: Horarios de atención (`get_opening_hours`).
        cancelled_id: Identificador de la cita cancelada (`cancel_appointment`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ToolName
    slots: list[Slot] = Field(default_factory=list)
    appointment: AppointmentView | None = None
    hours: list[OpeningHoursDay] = Field(default_factory=list)
    cancelled_id: str | None = None
