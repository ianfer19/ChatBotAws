"""Estado del grafo del supervisor: el contrato entre nodos (ROADMAP Paso 4).

`message` y `history` los pone el llamador con el contexto ya resuelto en el gateway;
el `history` es obligatorio en runtime (nodo `load_context` lo exige: requisito 7.2) y
queda como `NotRequired` solo para poder construir en los tests el turno negativo que
debe fallar. El resto de campos los escriben los nodos a medida que avanza el grafo.
"""

from typing import NotRequired, TypedDict

from shared.contracts import AgentName, CustomerContext, InboundMessage, Intent, RoutedTurn
from shared.ports import LLMMessage


class SupervisorState(TypedDict):
    """Estado tipado compartido por todos los nodos del grafo del supervisor.

    Campos:
        message: Mensaje normalizado del gateway (trae `tenant_id`, `correlation_id` y
            `customer_id` ya resueltos; nunca del payload del LLM).
        history: Ventana de historial recortada; obligatoria (guard en `load_context`).
        context: Contexto de cliente leído en el turno; lo escribe `load_context`.
        intent: Intención clasificada; la escribe `classify`.
        confidence: Confianza del clasificador (0 a 1); la escribe `classify`.
        target: Agente destino; lo escribe `decide`.
        reply: Respuesta directa del supervisor (saludo, degradación o servicio no
            disponible); la escriben `greet` y `decide`.
        routed: Turno enrutado al especialista; lo escriben `route_*`.
        route_error: Código del error de enrutado traducido a respuesta, si lo hubo.
    """

    message: InboundMessage
    history: NotRequired[list[LLMMessage]]
    context: NotRequired[CustomerContext]
    intent: NotRequired[Intent]
    confidence: NotRequired[float]
    target: NotRequired[AgentName]
    reply: NotRequired[str]
    routed: NotRequired[RoutedTurn]
    route_error: NotRequired[str]
