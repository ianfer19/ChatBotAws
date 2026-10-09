"""Ports que el dominio del supervisor necesita fuera de sí mismo (Protocol puros).

El supervisor no importa otros slices: recibe estos puertos ya compuestos desde fuera
(handler, REPL o tests). El lector de contexto lo implementa el slice `customer_context`
y el grafo de especialista es el grafo compilado de `appointments` (composición por
invocación, ADR 0010); la disciplina de aislamiento la verifica `lint-imports`.
"""

from typing import Any, Protocol, runtime_checkable

from shared.contracts import CustomerContext


@runtime_checkable
class ContextReaderPort(Protocol):
    """Lectura obligatoria del contexto de cliente en cada turno (requisito 7.2).

    La implementación real es `CustomerContextTools.get_customer_context`
    (slice `customer_context`): devuelve contexto vacío para clientes nuevos y para
    TTL vencido, nunca `None` en producción. `None` queda permitido en la firma para
    poder expresar el fallo «turno sin contexto» en tests.
    """

    def get_customer_context(self, *, tenant_id: str, customer_id: str) -> CustomerContext | None:
        """Devuelve el contexto del cliente o `None` si el turno llegó sin contexto.

        Args:
            tenant_id: Comercio resuelto en el gateway (nunca del payload del LLM).
            customer_id: Cliente normalizado del canal.

        Returns:
            El contexto del cliente, o `None` si no hay contexto para el turno.
        """
        ...


@runtime_checkable
class SpecialistGraphPort(Protocol):
    """Grafo de un especialista invocable desde el supervisor (nodo anidado, ADR 0010).

    Lo satisface el `CompiledStateGraph` de LangGraph devuelto por
    `build_appointment_graph` y cualquier doble con `.invoke`. Se usa `Any` a propósito:
    el contrato de entrada del especialista vive en su propio slice y aquí solo se
    invoca y se devuelve su resultado.
    """

    def invoke(self, input: Any) -> Any:
        """Ejecuta un turno completo del especialista.

        Args:
            input: Estado inicial con `tenant_id`, `correlation_id`, `user_message` e
                `history` (las claves que hoy exige el grafo de citas, Paso 3).

        Returns:
            Estado final del especialista; el supervisor lee `reply`.
        """
        ...
