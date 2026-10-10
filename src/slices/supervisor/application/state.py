"""Estado del grafo del supervisor: el contrato entre nodos (ROADMAP Paso 4).

`message` y `history` los pone el llamador con el contexto ya resuelto en el gateway;
el `history` es obligatorio en runtime (nodo `load_context` lo exige: requisito 7.2) y
queda como `NotRequired` solo para poder construir en los tests el turno negativo que
debe fallar. El resto de campos los escriben los nodos a medida que avanza el grafo.

Con checkpointer activo (Paso 8) el turno siguiente parte del state del turno anterior,
así que `window_history` vacía al empezar `reply`, `route_error` y `pending_outcome`
(campos de resultado): si no, la arista `ruta_tras_pendiente` cerraría el turno con una
respuesta vieja y un draft parecería resuelto. `routed` no se limpia: los consumidores
leen `pending_outcome` (si no es `None`), luego `reply` (si no es `None`) y solo
entonces `routed`.
"""

from typing import Literal, NotRequired, TypedDict

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
            disponible); la escriben `greet` y `decide`. `None` si el turno aún no ha
            respondido (se vacía al inicio cuando hay checkpointer).
        routed: Turno enrutado al especialista; lo escriben `route_*`; los
            consumidores solo lo leen si `reply` es `None`.
        route_error: Código del error de enrutado traducido a respuesta, si lo hubo.
        pending_outcome: Resolución de un draft pendiente hecha por `resolve_pending`
            (`affirmed`, `denied` u `undoed`); solo presente cuando el router cerró el
            turno sin pasar por `classify`.
        summary: Resumen rodante de los turnos que desbordaron la ventana (Paso 8);
            lo escribe `window_history` y lo conserva el checkpointer entre turnos.
    """

    message: InboundMessage
    history: NotRequired[list[LLMMessage]]
    summary: NotRequired[str | None]
    context: NotRequired[CustomerContext]
    intent: NotRequired[Intent]
    confidence: NotRequired[float]
    target: NotRequired[AgentName]
    reply: NotRequired[str | None]
    routed: NotRequired[RoutedTurn]
    route_error: NotRequired[str | None]
    pending_outcome: NotRequired[Literal["affirmed", "denied", "undoed"] | None]
