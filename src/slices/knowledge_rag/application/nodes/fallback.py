"""Nodo `fallback`: responde sin evidencia con el mensaje del dominio.

Camino degradado del turno: sale de código (`domain.rules.mensaje_fallback`),
jamás del modelo — un turno sin evidencia o con el almacén caído nunca invoca
el LLM (hay test que cuenta las llamadas).
"""

from slices.knowledge_rag.application.state import AgentState
from slices.knowledge_rag.domain.rules import mensaje_fallback


def fallback(state: AgentState) -> AgentState:
    """Escribe la respuesta honesta según el motivo de degradación del turno.

    Args:
        state: Turno con `fallback_reason` escrito por `retrieve` (si no viniera,
            responde como `sin_evidencia`: nunca un turno sin `reply`).

    Returns:
        Estado con `reply` ya redactado (sin pasar por el modelo).
    """
    razon = state.get("fallback_reason") or "sin_evidencia"
    return {**state, "reply": mensaje_fallback(razon)}
