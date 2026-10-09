"""Estado del grafo de citas (`AgentState`): el contrato entre nodos (ROADMAP Paso 3).

Los cuatro primeros campos son la entrada del turno y los pone el llamador con el
contexto ya resuelto en el gateway — nunca con lo que el LLM escriba. El resto los
escriben los nodos a medida que avanza el grafo; por eso son opcionales
(`NotRequired`) hasta que el nodo correspondiente se ejecuta.
"""

from typing import NotRequired, TypedDict

from shared.ports import LLMMessage
from slices.appointments.application.schemas import (
    AppointmentProposal,
    ToolName,
    ToolResult,
)


class AgentState(TypedDict):
    """Estado tipado compartido por todos los nodos del grafo de citas.

    Campos:
        tenant_id: Comercio resuelto en el gateway (contexto, no del LLM).
        correlation_id: Identificador del turno para logs e idempotencia.
        conversation_id: Conversación dueña de los drafts (un solo draft activo por
            ella; compuesto por el llamador hasta que el gateway la aporte, Paso 9).
        user_message: Texto del mensaje actual del cliente.
        history: Ventana de historial ya recortada (N=10; resumen en el Paso 8).
        proposal: Conclusión estructurada de `understand`.
        missing_fields: Campos obligatorios ausentes detectados en `validate`.
        tool_name: Tool elegida por `select_action` (allowlist del slice).
        tool_result: Salida de la tool ejecutada (única fuente de datos).
        tool_error: Error tipado de la tool, ya traducido (código + mensaje de log).
        needs_confirmation: Si el resultado exige confirmación del cliente.
        reply: Respuesta final redactada para el cliente.
    """

    tenant_id: str
    correlation_id: str
    conversation_id: str
    user_message: str
    history: NotRequired[list[LLMMessage]]
    proposal: NotRequired[AppointmentProposal]
    missing_fields: NotRequired[list[str]]
    tool_name: NotRequired[ToolName]
    tool_result: NotRequired[ToolResult]
    tool_error: NotRequired[dict[str, str]]
    needs_confirmation: NotRequired[bool]
    reply: NotRequired[str]
