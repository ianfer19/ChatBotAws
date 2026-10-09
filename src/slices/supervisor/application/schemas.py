"""Salida estructurada del clasificador y del router de pendientes: JSON estricto.

El LLM solo propone `intent` + `confidence` (o `decision` + `payload_hash` en el
router); cualquier clave de más, valor fuera de rango o valor fuera del contrato
invalida la respuesta y dispara el reintento del nodo (un fallo de formato no puede
acabar en una acción).
"""

from typing import Literal

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


class PendingAnswer(BaseModel):
    """Respuesta estructurada del LLM de respaldo del router de pendientes (ADR 0011.5).

    `payload_hash` es la defensa: el modelo debe eco el hash exacto de la propuesta que
    se le mostró; si el eco no coincide con el del draft, la plataforma ignora la
    decisión y el turno pasa al agente normal.

    Example:
        >>> PendingAnswer(decision="affirm", payload_hash="abc123").decision
        'affirm'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["affirm", "deny", "pass"]
    payload_hash: str = Field(min_length=1, max_length=128)
