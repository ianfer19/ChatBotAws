"""Doble en memoria de `MemoryStorePort`: conversaciones sin DynamoDB (Paso 8).

Mismo patrón que `InMemoryDraftStore`: implementa el port tal cual para que los
tests, los evals y el REPL prueben el checkpointer sin servicios externos. El doble
**ignora `ttl_seconds`** (no lleva reloj): la expiración real vive en el adapter de
DynamoDB del Paso 8.
"""

from shared.errors import ValidationError


class InMemoryMemoryStore:
    """Almacén de payloads por `(tenant_id, conversation_id)` en memoria.

    Example:
        >>> store = InMemoryMemoryStore()
        >>> store.put(tenant_id="t1", conversation_id="c1", payload='{"v": 1}')
        >>> store.get(tenant_id="t1", conversation_id="c1")
        '{"v": 1}'
        >>> store.get(tenant_id="otro", conversation_id="c1") is None
        True
    """

    def __init__(self) -> None:
        """Crea el almacén vacío (un dict por clave compuesta de tenant e hilo)."""
        self._payloads: dict[tuple[str, str], str] = {}

    def put(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        payload: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Guarda (o sobrescribe) el payload de una conversación.

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Conversación a escribir.
            payload: Estado serializado ya validado por quien lo escribió.
            ttl_seconds: Ignorado por el doble (sin reloj); el real lo aplica
                DynamoDB.

        Raises:
            ValidationError: Si falta `tenant_id` o `conversation_id`.
        """
        if not tenant_id or not conversation_id:
            raise ValidationError("escritura de memoria sin tenant_id o conversation_id")
        self._payloads[(tenant_id, conversation_id)] = payload

    def get(self, *, tenant_id: str, conversation_id: str) -> str | None:
        """Recupera el payload de una conversación del tenant indicado.

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Conversación a leer.

        Returns:
            El payload o `None` si no existe.
        """
        return self._payloads.get((tenant_id, conversation_id))

    def delete(self, *, tenant_id: str, conversation_id: str) -> None:
        """Borra la conversación; si no existe no hace nada.

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Conversación a borrar.
        """
        self._payloads.pop((tenant_id, conversation_id), None)
