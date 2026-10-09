"""Nodos del grafo de pedidos: funciones puras sobre `AgentState` con dependencias inyectadas.

Espejo de `appointments/application/nodes/__init__.py`: cada nodo recibe el estado
completo y devuelve un `AgentState` con los campos que escribe; LangGraph lo fusiona
con el estado anterior. El orden y las aristas viven en `application/graph.py`. Los
nodos no crean nada: LLM y tools llegan en `Deps`.
"""

from slices.orders.application.nodes.call_tool import call_tool
from slices.orders.application.nodes.respond import respond
from slices.orders.application.nodes.select_action import ruta_tras_accion, select_action
from slices.orders.application.nodes.understand import understand
from slices.orders.application.nodes.validate import need_more, validate
from slices.orders.application.nodes.validate_result import ruta_confirmacion, validate_result

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
