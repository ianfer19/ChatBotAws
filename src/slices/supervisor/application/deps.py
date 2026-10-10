"""Dependencias inyectadas en los nodos del grafo del supervisor (DI manual).

El constructor del grafo (`build_supervisor_graph`) recibe estos objetos y los reparte
con `partial`; el handler (Paso 9) los compone con los adaptadores reales y los tests
pasan dobles (ver `docs/architecture/HEXAGONAL_AND_SLICING.md`).
"""

from dataclasses import dataclass

from shared.contracts import AgentName
from shared.ports import DraftStorePort, LLMPort
from slices.supervisor.domain.ports import ConfirmerPort, ContextReaderPort, SpecialistGraphPort


@dataclass(frozen=True)
class Deps:
    """Lo que los nodos no pueden crear por sí mismos.

    Args:
        llm: Modelo clasificador (hoy `BedrockLLM`, en tests un doble guionizado).
        context_reader: Lector del contexto de cliente (tool de `customer_context`).
        allowed_bots: Entitlements del comercio: bots que tiene activados.
        appointments_graph: Grafo de citas ya compilado (invocado por `route_appointments`).
        orders_graph: Grafo de pedidos compilado (invocado por `route_orders`);
            `None` hasta que la composición lo inyecte (Fase 3 del Paso 5): sin él,
            los pedidos caen en `route_pending`.
        faq_graph: Grafo de respuestas de conocimiento compilado (invocado por
            `route_faq`, Paso 7); `None` hasta que la composición lo inyecte: sin
            él, el FAQ cae en `route_pending` (retrocompatible).
        draft_store: Store de drafts con el que `resolve_pending` lee el pendiente de
            la conversación (Fase 4 del Paso 5); `None` desactiva el router.
        confirmer: Resolución de drafts (affirm/deny/undo) que la composición despacha
            al especialista dueño del draft; `None` deja los turnos en el flujo
            normal (retrocompatible con composiciones previas).
        history_window_size: Tamaño máximo de la ventana de historial que ve el
            clasificador (Paso 8); lo que desborda se reduce a resumen.
    """

    llm: LLMPort
    context_reader: ContextReaderPort
    allowed_bots: frozenset[AgentName]
    appointments_graph: SpecialistGraphPort
    orders_graph: SpecialistGraphPort | None = None
    faq_graph: SpecialistGraphPort | None = None
    draft_store: DraftStorePort | None = None
    confirmer: ConfirmerPort | None = None
    history_window_size: int = 10
