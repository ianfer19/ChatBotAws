"""Nodo `greet`: la ruta propia del saludo (regla 1 del slice, regresión obligatoria).

Responde el supervisor con su plantilla neutral usando solo el branding del comercio;
no invoca especialistas ni tools y jamás sale hacia ventas. El branding por defecto es
el `tenant_id` hasta que el gateway resuelva el nombre comercial
(`TODO(decision)`, Paso 9).
"""

from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.routing import saludo


def greet(state: SupervisorState) -> SupervisorState:
    """Escribe la respuesta de saludo con `target = supervisor`.

    Args:
        state: Turno clasificado como `greeting`/`smalltalk`.

    Returns:
        Estado con `target` y `reply`; sin `routed` (nadie más interviene).
    """
    branding = state["message"].tenant_id
    return {**state, "target": "supervisor", "reply": saludo(branding)}
