"""Nodo `respond`: redacta la respuesta SOLO con la evidencia recuperada.

El `system` es la plantilla base + la tarea de fundamentación + el bloque de
evidencia; el historial y la pregunta viajan como mensajes. Si el LLM falla, el
error se propaga como en el resto de especialistas (lo gestiona el handler del
turno, Paso 9).
"""

from shared.ports import LLMMessage
from slices.knowledge_rag.application.deps import Deps
from slices.knowledge_rag.application.prompts import (
    TAREA_RESPONDER,
    bloque_evidencia,
    load_system_prompt,
)
from slices.knowledge_rag.application.state import AgentState


def respond(state: AgentState, *, deps: Deps) -> AgentState:
    """Redacta la respuesta fundamentada para el cliente.

    Args:
        state: Turno con `evidence` (la arista condicional solo llega aquí si
            hubo evidencia) y con la ventana `history` del supervisor.
        deps: LLM de redacción y tool ya cableados.

    Returns:
        Estado con `reply` ya limpio, listo para el canal.

    Raises:
        ToolError/ToolTimeoutError: Fallos del modelo; se propagan sin traducir
            aquí (gestiona el handler).
    """
    system = (
        f"{load_system_prompt()}\n\n{TAREA_RESPONDER}\n\n"
        f"{bloque_evidencia(state.get('evidence') or [])}"
    )
    mensajes = [
        *list(state.get("history") or []),
        LLMMessage(role="user", content=state["user_message"]),
    ]
    reply = deps.llm.invoke(messages=mensajes, system=system).text.strip()
    return {**state, "reply": reply}
