"""Modelos Pydantic de la aplicación: lo que el LLM propone y lo que devuelven las tools.

Viven en `application/` (decisión del Paso 3): los contratos públicos hacia otros slices
se publican en `shared/contracts/` cuando `supervisor` los necesite (Paso 4). Nada de
aquí viaja al `domain/`, que sigue sin conocer estos tipos. `OpeningHoursDay` se
re-exporta desde `domain/` porque lo necesita la regla de horario (Paso 5).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.pending import ConfirmationPolicy, DraftStatus
from slices.appointments.domain.hours import OpeningHoursDay

__all__ = [
    "AppointmentProposal",
    "AppointmentView",
    "OpeningHoursDay",
    "ProposalAction",
    "Slot",
    "ToolName",
    "ToolResult",
]

ToolName = Literal[
    "get_availability",
    "propose_appointment",
    "cancel_appointment",
    "get_opening_hours",
]
"""Tools que este grafo sabe ejecutar (allowlist; «LangGraph decide si puede usarla»).

Solo `propose_appointment` y `cancel_appointment` proponen escrituras y ambas lo hacen
como draft: ninguna tool escribe datos reales directamente (ADR 0011.1).
"""

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


class ToolResult(BaseModel):
    """Salida de una tool del grafo: la única fuente de datos de la respuesta.

    Args:
        tool: Tool que produjo el resultado (debe coincidir con la pedida).
        slots: Huecos libres (`get_availability`).
        appointment: Cita creada (`propose_appointment` con política `AUTO`).
        hours: Horarios de atención (`get_opening_hours`).
        cancelled_id: Identificador de la cita cancelada (`cancel_appointment`).
        draft_id: Draft asociado a la propuesta (solo tools de escritura).
        draft_status: Estado del draft en la máquina del ADR 0011.
        policy: Política aplicada (`AUTO` directo o `CONFIRM` a la espera).
        policy_reasons: Motivos de la política (logs, métricas y tests).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ToolName
    slots: list[Slot] = Field(default_factory=list)
    appointment: AppointmentView | None = None
    hours: list[OpeningHoursDay] = Field(default_factory=list)
    cancelled_id: str | None = None
    draft_id: str | None = None
    draft_status: DraftStatus | None = None
    policy: ConfirmationPolicy | None = None
    policy_reasons: tuple[str, ...] = ()
