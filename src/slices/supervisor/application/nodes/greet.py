"""Nodo `greet`: la ruta propia del saludo (regla 1 del slice, regresión obligatoria).

Responde el supervisor con su plantilla neutral usando solo el branding del comercio;
no invoca especialistas ni tools y jamás sale hacia ventas. El nombre comercial llega
por `Deps.tenant_name` (Fase A de la consola); si no está, se conserva el `tenant_id`
como respaldo.
"""

from slices.supervisor.application.deps import Deps
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.routing import saludo


def greet(state: SupervisorState, *, deps: Deps) -> SupervisorState:
    """Escribe la respuesta de saludo con `target = supervisor`.

    Args:
        state: Turno clasificado como `greeting`/`smalltalk`.
        deps: Dependencias del grafo; de ahí sale el nombre comercial del saludo.

    Returns:
        Estado con `target` y `reply`; sin `routed` (nadie más interviene).
    """
    branding = deps.tenant_name or state["message"].tenant_id
    return {**state, "target": "supervisor", "reply": saludo(branding)}
