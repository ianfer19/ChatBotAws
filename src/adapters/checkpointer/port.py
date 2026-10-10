"""Checkpointer de LangGraph persistido tras `MemoryStorePort` (Paso 8).

`PortCheckpointSaver` adapta la API de `langgraph.checkpoint.base.BaseCheckpointSaver`
(verificada contra langgraph 1.2.14 + langgraph-checkpoint 4.2.0, instalados en el
repo) a las tres operaciones de `MemoryStorePort`: cada conversación es **un único
payload JSON** con el checkpoint más reciente y sus writes pendientes.

Decisiones de diseño (por qué, no qué):

- **Solo el checkpoint más reciente**: los grafos de este repo no usan `interrupt()`
  ni time-travel; se restaura el último estado de la conversación. `parent_config` se
  conserva como referencia, pero sus antepasados no se almacenan — `TODO(verify)` si
  algún flujo futuro necesita ramificación o salto temporal.
- **`thread_id` con tenant embebido**: formato ``<tenant_id>#<conversation_id>``
  (ver `thread_id_de`). El tenant lo pone el llamador que resolvió el contexto en el
  gateway, nunca el payload del LLM; el saver lo exige para poder partir el hilo en la
  clave compuesta del port (el port no enumera conversaciones, así que también permite
  `delete_thread` sin estado auxiliar).
- **Envelope JSON con serde de LangGraph**: los tipos no JSON (datetime, bytes) viajan
  con `JsonPlusSerializer` (msgpack) codificado en base64 dentro del JSON, que es lo
  que exige `MemoryStorePort.payload: str`.

Example:
    >>> from adapters.in_memory import InMemoryMemoryStore
    >>> saver = PortCheckpointSaver(store=InMemoryMemoryStore())
    >>> thread = thread_id_de(tenant_id="Sede_Elite_01", conversation_id="c-1")
    >>> _ = saver.get_tuple({"configurable": {"thread_id": thread, "checkpoint_ns": ""}})
"""

import base64
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    RunnableConfig,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.base import SerializerProtocol

from shared.errors import ValidationError
from shared.logging import get_logger
from shared.ports import MemoryStorePort

_logger = get_logger(__name__)

_VERSION_ENVELOPE = 1
_SEPARADOR = "#"


def thread_id_de(*, tenant_id: str, conversation_id: str) -> str:
    """Construye el `thread_id` de LangGraph con el tenant embebido.

    Args:
        tenant_id: Comercio dueño de la conversación (del contexto resuelto).
        conversation_id: Identificador de la conversación.

    Returns:
        ``<tenant_id>#<conversation_id>``.

    Raises:
        ValidationError: Si falta algún campo o si alguno contiene el separador.
    """
    if not tenant_id or not conversation_id:
        raise ValidationError("thread_id sin tenant_id o conversation_id")
    if _SEPARADOR in tenant_id or _SEPARADOR in conversation_id:
        raise ValidationError(
            "tenant_id o conversation_id contienen el separador '#'",
            details={"tenant_id": tenant_id},
        )
    return f"{tenant_id}{_SEPARADOR}{conversation_id}"


def _partes(thread_id: str | None) -> tuple[str, str]:
    """Separa un `thread_id` en tenant y conversación.

    Args:
        thread_id: Hilo recibido de la configuración de LangGraph.

    Returns:
        Tupla `(tenant_id, conversation_id)`.

    Raises:
        ValidationError: Si el hilo no tiene el formato ``<tenant>#<conv>``.
    """
    if not thread_id or _SEPARADOR not in thread_id:
        raise ValidationError(
            "thread_id debe tener el formato '<tenant_id>#<conversation_id>'",
            details={"thread_id": thread_id or ""},
        )
    tenant_id, _, conversation_id = thread_id.partition(_SEPARADOR)
    if not tenant_id or not conversation_id:
        raise ValidationError(
            "thread_id con partes vacias",
            details={"thread_id": thread_id},
        )
    return tenant_id, conversation_id


class PortCheckpointSaver(BaseCheckpointSaver[str]):
    """Checkpointer sincrónico que persiste cada hilo en un `MemoryStorePort`.

    El payload de cada conversación es JSON puro (`str`), por lo que se puede
    inspeccionar en un test sin dependencias externas.

    Args:
        store: Almacén tras el port (doble en memoria o DynamoDB).
        ttl_seconds: Caducidad opcional del payload; `None` no expira
            (la retención concreta es `TODO(decision)` con ADR 0007).
        serde: Serializer de LangGraph; por defecto `JsonPlusSerializer`.
    """

    def __init__(
        self,
        *,
        store: MemoryStorePort,
        ttl_seconds: int | None = None,
        serde: SerializerProtocol | None = None,
    ) -> None:
        super().__init__(serde=serde)
        self._store = store
        self._ttl_seconds = ttl_seconds

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Carga el checkpoint más reciente del hilo indicado.

        Args:
            config: Configuración con `thread_id` (y opcionalmente un
                `checkpoint_id` concreto).

        Returns:
            La tupla del checkpoint recién guardado, o `None` si el hilo no
            existe o se pidió un checkpoint distinto del más reciente (el
            saver no conserva la cadena completa).

        Raises:
            ValidationError: Si falta el hilo o el payload está corrupto.
            ToolError: Si el almacén falla (lo traduce el adapter del port).
        """
        tenant_id, conversation_id = self._claves(config)
        envelope = self._cargar(tenant_id=tenant_id, conversation_id=conversation_id)
        if envelope is None:
            return None
        checkpoint = self._decodifica(envelope["checkpoint"])
        pedido = get_checkpoint_id(config)
        if pedido is not None and pedido != envelope["checkpoint_id"]:
            return None
        ns = self._ns(config)
        thread_id = str((config.get("configurable") or {}).get("thread_id", ""))
        actual = self._config(thread_id=thread_id, ns=ns, checkpoint_id=envelope["checkpoint_id"])
        padre = envelope.get("parent_id")
        writes = [
            (
                registro["task"],
                registro["channel"],
                self._decodifica(registro["value"]),
            )
            for registro in envelope.get("writes", [])
        ]
        return CheckpointTuple(
            config=actual,
            checkpoint=checkpoint,
            metadata=self._decodifica(envelope["metadata"]),
            parent_config=(
                self._config(thread_id=thread_id, ns=ns, checkpoint_id=str(padre))
                if padre
                else None
            ),
            pending_writes=writes,
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """Enumera (como mucho) el checkpoint reciente del hilo pedido.

        El port no admite listar conversaciones, así que `config=None` no
        devuelve nada y listar exige `thread_id`.

        Args:
            config: Configuración con `thread_id`; `None` no lista nada.
            filter: Pares clave-valor que deben coincidir con la metadata.
            before: Si se pasa, omite checkpoints con id mayor o igual.
            limit: Máximo de resultados (`<= 0` no devuelve nada).

        Yields:
            La tupla del checkpoint si satisface los filtros.
        """
        if config is None:
            return
        if limit is not None and limit <= 0:
            return
        tupla = self.get_tuple(config)
        if tupla is None:
            return
        if (
            before
            and (checkpoint_before := get_checkpoint_id(before))
            and tupla.checkpoint["id"] >= checkpoint_before
        ):
            return
        if filter and not all(
            query == tupla.metadata.get(query_key) for query_key, query in filter.items()
        ):
            return
        yield tupla

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Guarda el checkpoint como estado vigente del hilo (reemplaza al anterior).

        Args:
            config: Configuración vigente; su `checkpoint_id` queda como padre.
            checkpoint: Checkpoint nuevo (con sus `channel_values` en línea).
            metadata: Metadata del paso que LangGraph pide registrar.
            new_versions: Ignorado a propósito: al guardar los
                `channel_values` en línea no hay blobs por versión que
                deduplicar.

        Returns:
            Configuración apuntando al checkpoint recién guardado.

        Raises:
            ValidationError: Si el hilo no trae tenant o el payload está corrupto.
        """
        tenant_id, conversation_id = self._claves(config)
        pendientes: list[dict[str, Any]] = []
        envelope: dict[str, Any] = {
            "v": _VERSION_ENVELOPE,
            "checkpoint_id": checkpoint["id"],
            "checkpoint": self._codifica(checkpoint),
            "metadata": self._codifica(get_checkpoint_metadata(config, metadata)),
            "parent_id": get_checkpoint_id(config),
            "writes": pendientes,
        }
        self._guardar(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            envelope=envelope,
        )
        _logger.debug(
            "checkpointer.put",
            extra={
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "checkpoint_id": checkpoint["id"],
            },
        )
        return self._config(
            thread_id=str((config.get("configurable") or {}).get("thread_id", "")),
            ns=self._ns(config),
            checkpoint_id=checkpoint["id"],
        )

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Adjunta writes pendientes al checkpoint vigente del hilo.

        Args:
            config: Configuración del checkpoint que consumirá los writes.
            writes: Pares `(canal, valor)` escritos por la tarea.
            task_id: Identificador de la tarea que escribe.
            task_path: Ruta de la tarea dentro del grafo.

        Raises:
            ValidationError: Si el hilo no trae tenant o el payload está corrupto.
        """
        tenant_id, conversation_id = self._claves(config)
        envelope = self._cargar(tenant_id=tenant_id, conversation_id=conversation_id)
        checkpoint_id = (config.get("configurable") or {}).get("checkpoint_id")
        if envelope is None or checkpoint_id != envelope["checkpoint_id"]:
            _logger.debug(
                "checkpointer.write_descartado",
                extra={
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "checkpoint_id": str(checkpoint_id),
                },
            )
            return
        existentes = {(registro["task"], registro["idx"]) for registro in envelope["writes"]}
        for indice, (canal, valor) in enumerate(writes):
            efectivo = WRITES_IDX_MAP.get(canal, indice)
            if efectivo >= 0 and (task_id, efectivo) in existentes:
                continue
            envelope["writes"].append(
                {
                    "task": task_id,
                    "channel": canal,
                    "idx": efectivo,
                    "path": task_path,
                    "value": self._codifica(valor),
                }
            )
            existentes.add((task_id, efectivo))
        self._guardar(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            envelope=envelope,
        )

    def delete_thread(self, thread_id: str) -> None:
        """Borra todo el estado guardado de una conversación.

        Args:
            thread_id: Hilo con formato ``<tenant_id>#<conversation_id>``.

        Raises:
            ValidationError: Si el hilo no tiene el formato esperado.
        """
        tenant_id, conversation_id = _partes(thread_id)
        self._store.delete(tenant_id=tenant_id, conversation_id=conversation_id)
        _logger.debug(
            "checkpointer.delete",
            extra={"tenant_id": tenant_id, "conversation_id": conversation_id},
        )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Versión asíncrona de `get_tuple` (delega en la sincrónica)."""
        return self.get_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Versión asíncrona de `list` (delega en la sincrónica)."""
        for tupla in self.list(config, filter=filter, before=before, limit=limit):
            yield tupla

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Versión asíncrona de `put` (delega en la sincrónica)."""
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Versión asíncrona de `put_writes` (delega en la sincrónica)."""
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        """Versión asíncrona de `delete_thread` (delega en la sincrónica)."""
        self.delete_thread(thread_id)

    def _claves(self, config: RunnableConfig) -> tuple[str, str]:
        """Extrae `(tenant_id, conversation_id)` del `thread_id` de la config.

        Args:
            config: Configuración de LangGraph del turno.

        Returns:
            Tupla `(tenant_id, conversation_id)`.

        Raises:
            ValidationError: Si falta el hilo o no trae tenant.
        """
        return _partes((config.get("configurable") or {}).get("thread_id"))

    @staticmethod
    def _ns(config: RunnableConfig) -> str:
        """Devuelve el `checkpoint_ns` de la config (vacío si no viene).

        Args:
            config: Configuración de LangGraph del turno.

        Returns:
            El namespace del checkpoint.
        """
        return str((config.get("configurable") or {}).get("checkpoint_ns", ""))

    @staticmethod
    def _config(*, thread_id: str, ns: str, checkpoint_id: str) -> RunnableConfig:
        """Construye una `RunnableConfig` apuntando a un checkpoint concreto.

        Args:
            thread_id: Hilo completo con tenant.
            ns: Namespace del checkpoint.
            checkpoint_id: Identificador del checkpoint.

        Returns:
            Configuración lista para devolver a LangGraph.
        """
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def _codifica(self, valor: Any) -> dict[str, str]:
        """Serializa un valor con el serde de LangGraph a un registro JSON.

        Args:
            valor: Objeto a guardar (puede contener datetime, bytes...).

        Returns:
            Dict `{"t": etiqueta, "b": base64}`.
        """
        etiqueta, datos = self.serde.dumps_typed(valor)
        return {"t": etiqueta, "b": base64.b64encode(datos).decode("ascii")}

    def _decodifica(self, registro: dict[str, Any]) -> Any:
        """Recupera un valor serializado por `_codifica`.

        Args:
            registro: Dict `{"t": etiqueta, "b": base64}`.

        Returns:
            El objeto original.
        """
        return self.serde.loads_typed((str(registro["t"]), base64.b64decode(str(registro["b"]))))

    def _cargar(self, *, tenant_id: str, conversation_id: str) -> dict[str, Any] | None:
        """Lee y valida el envelope JSON de una conversación.

        Args:
            tenant_id: Comercio dueño.
            conversation_id: Conversación a leer.

        Returns:
            El envelope o `None` si la conversación no existe.

        Raises:
            ValidationError: Si el payload no es un envelope válido.
            ToolError: Si el almacén falla (lo traduce el adapter del port).
        """
        payload = self._store.get(tenant_id=tenant_id, conversation_id=conversation_id)
        if payload is None:
            return None
        try:
            envelope = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "payload de checkpoint que no es JSON",
                details={"conversation_id": conversation_id},
            ) from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("v") != _VERSION_ENVELOPE
            or "checkpoint" not in envelope
            or "metadata" not in envelope
        ):
            raise ValidationError(
                "payload de checkpoint con envelope desconocido",
                details={"conversation_id": conversation_id},
            )
        return envelope

    def _guardar(self, *, tenant_id: str, conversation_id: str, envelope: dict[str, Any]) -> None:
        """Escribe el envelope como payload de la conversación.

        Args:
            tenant_id: Comercio dueño.
            conversation_id: Conversación a sobrescribir.
            envelope: Envelope ya construido.

        Raises:
            ToolError: Si el almacén falla (lo traduce el adapter del port).
        """
        self._store.put(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            payload=json.dumps(envelope, ensure_ascii=True),
            ttl_seconds=self._ttl_seconds,
        )
