"""Ports que el dominio del supervisor necesita fuera de sí mismo (Protocol puros).

El supervisor no importa otros slices: recibe estos puertos ya compuestos desde fuera
(handler, REPL o tests). El lector de contexto lo implementa el slice `customer_context`
y el grafo de especialista es el grafo compilado de `appointments`/`orders` (composición
por invocación, ADR 0010); el `ConfirmerPort` lo implementa la composición despachando al
especialista dueño del draft (`kind`). La disciplina de aislamiento la verifica
`lint-imports`.
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


@runtime_checkable
class ConfirmerPort(Protocol):
    """Operaciones de resolución de drafts que el router hace sin invocar al agente (ADR 0011.5).

    La implementación real vive en la composición (REPL/handler): despacha por el
    `kind` del draft al `confirm_draft`/`cancel_draft`/`undo_draft` del especialista
    dueño. La **modificación** de una propuesta no pasa por aquí: la gestiona el propio
    especialista al proponer de nuevo (un draft activo reemplaza al anterior y lo deja
    `SUPERSEDED`).

    Todas las operaciones exigen el `payload_hash` o el `draft_id` correctos dentro del
    comercio: un «sí» ligado a otro contenido no valida.
    """

    def affirm(self, *, tenant_id: str, draft_id: str, payload_hash: str) -> None:
        """Confirma y ejecuta un draft `AWAITING_CONFIRMATION` de este comercio.

        Args:
            tenant_id: Comercio dueño del draft (siempre del contexto).
            draft_id: Draft a confirmar.
            payload_hash: Hash del contenido exacto que el cliente confirmó.

        Raises:
            AppError: `DraftNotFound`, `DraftNotCommittable` o hash desfasado; el
                nodo `resolve_pending` lo degrada a turno normal con log.
        """
        ...

    def deny(self, *, tenant_id: str, draft_id: str) -> None:
        """Cancela un draft activo sin ejecutarlo («no» del cliente).

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft a cancelar.

        Raises:
            AppError: `DraftNotFound` o `DraftNotCommittable` (ya no está activo).
        """
        ...

    def undo(self, *, tenant_id: str, draft_id: str) -> None:
        """Deshace dentro de su ventana el draft ya commiteado («cancelar» tardío).

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft commiteado a deshacer.

        Raises:
            AppError: `DraftNotFound` o `DraftNotCommittable` (fuera de la ventana de
                deshacer o el pedido/cita ya no admite cambios).
        """
        ...
