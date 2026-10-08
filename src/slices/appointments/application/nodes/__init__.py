"""Nodos del grafo de citas: funciones puras sobre `AgentState` con dependencias inyectadas.

Cada nodo recibe el estado completo y devuelve un `AgentState` con los campos que
escribe; LangGraph lo fusiona con el estado anterior. El orden y las aristas viven en
`application/graph.py` (ROADMAP Paso 3). Los nodos no crean nada: LLM y tools llegan en
`Deps`.
"""

from slices.appointments.application.nodes.call_tool import call_tool
from slices.appointments.application.nodes.respond import respond
from slices.appointments.application.nodes.select_action import ruta_tras_accion, select_action
from slices.appointments.application.nodes.understand import understand
from slices.appointments.application.nodes.validate import need_more, validate
from slices.appointments.application.nodes.validate_result import ruta_confirmacion, validate_result

__all__ = [
    "call_tool",
    "need_more",
    "respond",
    "ruta_confirmacion",
    "ruta_tras_accion",
    "select_action",
    "understand",
    "validate",
    "validate_result",
]
