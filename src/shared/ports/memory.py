"""Persistencia de estado de conversación tras un port (Paso 8: checkpointer y ventana).

Es el almacén **genérico** de detrás del checkpointer de LangGraph y de las políticas
de ventana/resumen: guarda y recupera un payload opaco (JSON serializado) por
conversación, siempre particionado por `tenant_id`. No interpreta el contenido: eso
lo decide la capa que lo usa (el orquestador y sus políticas).

El consumidor concreto es `adapters.checkpointer.PortCheckpointSaver`
(`BaseCheckpointSaver` de langgraph-checkpoint 4.2.0, API verificada en el Paso 8):
cada conversación es **un solo payload** con el checkpoint más reciente y sus writes
pendientes; el `thread_id` de LangGraph lleva el tenant embebido (`<tenant>#<conv>`).
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryStorePort(Protocol):
    """Lectura/escritura del estado de una conversación, aislada por tenant."""

    def put(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        payload: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Guarda (o sobrescribe) el estado de una conversación.

        Args:
            tenant_id: Comercio dueño de la conversación; forma parte de la clave.
            conversation_id: Identificador de la conversación (thread del orquestador).
            payload: Estado serializado (JSON) ya validado por quien lo escribió.
            ttl_seconds: Caducidad opcional en segundos; `None` no expira.

        Raises:
            ToolError: Si la escritura falla (lo traduce el adapter).
            ValidationError: Si faltan `tenant_id` o `conversation_id`.
        """
        ...

    def get(self, *, tenant_id: str, conversation_id: str) -> str | None:
        """Recupera el estado de una conversación del tenant indicado.

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Identificador de la conversación.

        Returns:
            El payload serializado o `None` si no existe o ya caducó.

        Raises:
            ToolError: Si la lectura falla (lo traduce el adapter).
        """
        ...

    def delete(self, *, tenant_id: str, conversation_id: str) -> None:
        """Borra el estado de una conversación (borrado o cierre de sesión).

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Identificador de la conversación.

        Raises:
            ToolError: Si el borrado falla (lo traduce el adapter).
        """
        ...
