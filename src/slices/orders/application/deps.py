"""Dependencias inyectadas en los nodos del grafo (DI manual, sin framework).

El `handler` (Paso 9) construye estos objetos con los adaptadores reales y los pasa a
`build_order_graph`; los tests pasan dobles de una línea (ver
`docs/architecture/HEXAGONAL_AND_SLICING.md`).
"""

from dataclasses import dataclass

from shared.ports import ClockPort, LLMPort
from slices.orders.application.schemas import ToolName
from slices.orders.application.tools import OrderTools


@dataclass(frozen=True)
class Deps:
    """Lo que los nodos no pueden crear por sí mismos.

    Args:
        llm: Modelo de lenguaje (hoy `BedrockLLM`, en tests un doble guionizado).
        tools: Tools de pedidos con sus puertos (legacy, catálogo, drafts y horario).
        clock: Reloj del turno: `understand` le pasa «ahora» al prompt (horario de
            cocina) y las tools miden con él la ventana de deshacer.
        allowed_tools: Entitlements finos del comercio (Fase 4 del Paso 5); `None`
            permite toda la allowlist del slice. La composición los deriva de
            `allowed_bots` del supervisor; `select_action` interseca con
            `ALLOWED_TOOLS`, así que una tool fuera de la intersección no se ejecuta
            jamás (capa adicional de mínimo privilegio).
    """

    llm: LLMPort
    tools: OrderTools
    clock: ClockPort
    allowed_tools: frozenset[ToolName] | None = None
