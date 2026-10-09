"""Nodos del grafo del supervisor: funciones puras sobre `SupervisorState` con DI.

Cada nodo recibe el estado completo y devuelve el trozo que escribe; LangGraph lo
fusiona con el estado anterior. El orden y las aristas viven en `application/graph.py`
(ROADMAP Paso 4). Los nodos no crean nada: LLM, lector de contexto, entitlements y el
grafo de citas llegan en `Deps`.
"""

from slices.supervisor.application.nodes.classify import classify
from slices.supervisor.application.nodes.decide import decide
from slices.supervisor.application.nodes.greet import greet
from slices.supervisor.application.nodes.load_context import load_context
from slices.supervisor.application.nodes.route_appointments import route_appointments
from slices.supervisor.application.nodes.route_pending import route_pending
from slices.supervisor.application.state import SupervisorState

__all__ = [
    "classify",
    "decide",
    "greet",
    "load_context",
    "route_appointments",
    "route_pending",
    "ruta_tras_decidir",
]


def ruta_tras_decidir(state: SupervisorState) -> str:
    """Arista condicional tras `decide`: saludo, especialista, pendiente o fin.

    Args:
        state: Estado con `route_error` (respuesta directa), `target` o ninguno de los
            dos (no debería ocurrir: `decide` siempre escribe uno de los dos).

    Returns:
        `"greet"`, `"route_appointments"`, `"route_pending"` o `"end"`.
    """
    if state.get("route_error"):
        return "end"
    destino = state.get("target")
    if destino == "supervisor":
        return "greet"
    if destino == "appointments":
        return "route_appointments"
    return "route_pending"
