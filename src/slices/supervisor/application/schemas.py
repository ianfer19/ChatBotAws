"""Salida estructurada del clasificador del supervisor: JSON estricto validado.

El LLM solo propone `intent` + `confidence`; cualquier clave de más, valor fuera de
rango o intento fuera del contrato `Intent` invalida la respuesta y dispara el
reintento del nodo `classify` (un fallo de formato no puede acabar en una acción).
"""

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts import Intent


class SupervisorDecision(BaseModel):
    """Decisión de clasificación de un turno: intención y su confianza.

    Example:
        >>> SupervisorDecision(intent="greeting", confidence=0.97).intent
        'greeting'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
