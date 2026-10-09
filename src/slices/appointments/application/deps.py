"""Dependencias inyectadas en los nodos del grafo (DI manual, sin framework).

El `handler` (Paso 9) construye estos objetos con los adaptadores reales y los pasa a
`build_appointment_graph`; los tests pasan dobles de una línea (ver
`docs/architecture/HEXAGONAL_AND_SLICING.md`).
"""

from dataclasses import dataclass

from shared.ports import ClockPort, LLMPort
from slices.appointments.application.schemas import ToolName
from slices.appointments.application.tools import AppointmentTools


@dataclass(frozen=True)
class Deps:
    """Lo que los nodos no pueden crear por sí mismos.

    Args:
        llm: Modelo de lenguaje (hoy `BedrockLLM`, en tests un doble guionizado).
        tools: Tools de citas con sus puertos (repositorio, reloj y horario).
        clock: Reloj del turno: `understand` le pasa «hoy» al prompt (bug de fecha).
        allowed_tools: Entitlements finos del comercio (Fase 4 del Paso 5); `None`
            permite toda la allowlist del slice. La composición los deriva de
            `allowed_bots` del supervisor; `select_action` interseca con
            `ALLOWED_TOOLS`, así que una tool fuera de la intersección no se ejecuta
            jamás (capa adicional de mínimo privilegio).
    """

    llm: LLMPort
    tools: AppointmentTools
    clock: ClockPort
    allowed_tools: frozenset[ToolName] | None = None
