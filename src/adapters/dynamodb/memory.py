"""Adapter de DynamoDB para el estado de conversación tras `MemoryStorePort` (Paso 8).

`DynamoDBMemoryStore` es el almacén real detrás de `PortCheckpointSaver`: guarda un
payload opaco (JSON ya serializado) por conversación, particionado por `tenant_id`
(`PK=ORG#<tenant>` / `SK=CONV#<conversation>`, ver
[DATA_MODEL](../../../docs/architecture/DATA_MODEL.md)) con TTL opcional. El
payload nunca se loguea: solo los ids.

Errores: `ClientError`/`BotoCoreError` se traducen a `ToolError` y los timeouts de
conexión/lectura a `ToolTimeoutError`; jamás se fuga `botocore` al dominio.
"""

import time
from typing import Any, NoReturn, Protocol, cast, runtime_checkable

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.logging import get_logger

_logger = get_logger(__name__)

_DYNAMODB_SERVICE = "dynamodb"


@runtime_checkable
class DynamoDBClient(Protocol):
    """Subconjunto de `dynamodb` que usa este adapter (DI y dobles de test)."""

    def put_item(self, *, TableName: str, Item: dict[str, Any]) -> dict[str, Any]:
        """Escribe (o sobrescribe) un ítem.

        Args:
            TableName: Tabla destino.
            Item: Atributos del ítem (`PK`, `SK`, `payload` y `ttl` opcional).

        Returns:
            Respuesta vacía de DynamoDB en operaciones correctas.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...

    def get_item(
        self, *, TableName: str, Key: dict[str, Any], ConsistentRead: bool = ...
    ) -> dict[str, Any]:
        """Lee un ítem por su clave.

        Args:
            TableName: Tabla origen.
            Key: Clave del ítem (`PK` + `SK`).
            ConsistentRead: Lectura fuerte para no ver un checkpoint viejo.

        Returns:
            Diccionario con `Item` si existe; vacío si no.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...

    def delete_item(self, *, TableName: str, Key: dict[str, Any]) -> dict[str, Any]:
        """Borra un ítem por su clave (idempotente si no existía).

        Args:
            TableName: Tabla destino.
            Key: Clave del ítem (`PK` + `SK`).

        Returns:
            Respuesta vacía de DynamoDB en operaciones correctas.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


def _default_client(timeout_seconds: int) -> DynamoDBClient:
    """Crea el cliente `dynamodb` con timeout y reintentos limitados.

    Args:
        timeout_seconds: Segundos de espera de conexión y de lectura.

    Returns:
        Cliente listo para `put_item`/`get_item`/`delete_item`.

    TODO(verify): nombres exactos de `Config` (`connect_timeout`, `read_timeout`,
    `retries.mode`) y número de reintentos, verificados contra la doc de botocore.
    """
    config = Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    # boto3 no tiene stubs: la anotación es la que garantiza la firma del protocolo.
    cliente: DynamoDBClient = boto3.client(_DYNAMODB_SERVICE, config=config)
    return cliente


def _claves(*, tenant_id: str, conversation_id: str) -> dict[str, str]:
    """Construye la clave del ítem con los prefijos de DATA_MODEL.

    Args:
        tenant_id: Comercio dueño de la conversación.
        conversation_id: Identificador de la conversación (thread del orquestador).

    Returns:
        `{"PK": "ORG#...", "SK": "CONV#..."}`.

    Raises:
        ValidationError: Si falta el tenant o la conversación (partición obligatoria).
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacio en el almacén de checkpoints")
    if not conversation_id:
        raise ValidationError("conversation_id vacia en el almacén de checkpoints")
    return {"PK": f"ORG#{tenant_id}", "SK": f"CONV#{conversation_id}"}


def _traducir(exc: Exception, *, operacion: str, tenant_id: str) -> NoReturn:
    """Traduce una excepción de botocore al error tipado del sistema.

    Args:
        exc: Excepción original capturada del cliente.
        operacion: Nombre de la operación que falló (`put`, `get`, `delete`).
        tenant_id: Comercio, para el log estructurado.

    Raises:
        ToolTimeoutError: Si fue un timeout de conexión o de lectura.
        ToolError: Para cualquier otro fallo de red o de negocio (el original va
            en `__cause__`, nunca se filtra al usuario final).
    """
    if isinstance(exc, ConnectTimeoutError | ReadTimeoutError):
        raise ToolTimeoutError(
            "timeout de dynamodb en el estado de conversacion",
            details={"operacion": operacion, "tenant_id": tenant_id},
        ) from exc
    if isinstance(exc, ClientError):
        # `cast` explícito: el estrechamiento del isinstance no siempre lo capta
        # el chequeo estático alternativo (pyrefly), y el tipo es inequívoco aquí.
        error = cast(ClientError, exc)
        codigo = str(error.response.get("Error", {}).get("Code", "desconocido"))
        raise ToolError(
            "dynamodb rechazo la operacion de checkpoints",
            details={"operacion": operacion, "tenant_id": tenant_id, "codigo": codigo},
        ) from exc
    raise ToolError(
        "dynamodb no respondio en el estado de conversacion",
        details={"operacion": operacion, "tenant_id": tenant_id},
    ) from exc


class DynamoDBMemoryStore:
    """Implementación DynamoDB de `MemoryStorePort` (una tabla por ambiente).

    Satisface el port estructuralmente (sin heredarlo), al estilo de los demás
    adapters: quien compone puede anotar `store: MemoryStorePort = ...`.

    Args:
        table_name: Nombre real de la tabla (`chatbot_checkpoints_<ambiente>`);
            suele venir de `Settings.checkpoints_table`.
        timeout_seconds: Timeout de conexión y de lectura del cliente.
        client: Cliente inyectable (doble de test); `None` crea el real con boto3.

    Raises:
        ValidationError: Si `table_name` está vacío (fail fast de composición).
    """

    def __init__(
        self,
        *,
        table_name: str,
        timeout_seconds: int = 5,
        client: DynamoDBClient | None = None,
    ) -> None:
        if not table_name:
            raise ValidationError("nombre de tabla de checkpoints vacio")
        self._tabla = table_name
        self._cliente = client if client is not None else _default_client(timeout_seconds)

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
            conversation_id: Identificador de la conversación.
            payload: Estado serializado (JSON) ya validado por quien lo escribió.
            ttl_seconds: Caducidad opcional en segundos; `None` no expira.

        Raises:
            ValidationError: Si faltan `tenant_id`, `conversation_id` o el `ttl`
                es negativo.
            ToolError: Si DynamoDB rechaza la escritura o falla la red.
            ToolTimeoutError: Si la escritura excede el timeout del cliente.
        """
        item: dict[str, Any] = {**_claves(tenant_id=tenant_id, conversation_id=conversation_id)}
        item["payload"] = payload
        if ttl_seconds is not None:
            if ttl_seconds < 0:
                raise ValidationError(
                    "ttl_seconds negativo en el almacén de checkpoints",
                    details={"tenant_id": tenant_id},
                )
            item["ttl"] = int(time.time()) + ttl_seconds
        try:
            self._cliente.put_item(TableName=self._tabla, Item=item)
        except (BotoCoreError, ClientError) as exc:
            _traducir(exc, operacion="put", tenant_id=tenant_id)
        _logger.info(
            "dynamodb.checkpoint_put",
            extra={"tenant_id": tenant_id, "conversation_id": conversation_id},
        )

    def get(self, *, tenant_id: str, conversation_id: str) -> str | None:
        """Recupera el estado de una conversación del tenant indicado.

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Identificador de la conversación.

        Returns:
            El payload serializado, o `None` si no existe o su TTL ya venció
            (DynamoDB borra de forma asíncrona, así que también se comprueba aquí).

        Raises:
            ToolError: Si DynamoDB falla o el payload no es texto.
            ToolTimeoutError: Si la lectura excede el timeout del cliente.
        """
        try:
            respuesta = self._cliente.get_item(
                TableName=self._tabla,
                Key=_claves(tenant_id=tenant_id, conversation_id=conversation_id),
                ConsistentRead=True,
            )
        except (BotoCoreError, ClientError) as exc:
            _traducir(exc, operacion="get", tenant_id=tenant_id)
        item = respuesta.get("Item")
        if not item:
            return None
        ttl = item.get("ttl")
        if isinstance(ttl, int | float) and ttl <= time.time():
            return None
        payload = item.get("payload")
        if not isinstance(payload, str):
            raise ToolError(
                "payload de checkpoints no es texto",
                details={"tenant_id": tenant_id, "conversation_id": conversation_id},
            )
        return payload

    def delete(self, *, tenant_id: str, conversation_id: str) -> None:
        """Borra el estado de una conversación (borrado o cierre de sesión).

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Identificador de la conversación.

        Raises:
            ToolError: Si DynamoDB rechaza el borrado o falla la red.
            ToolTimeoutError: Si el borrado excede el timeout del cliente.
        """
        try:
            self._cliente.delete_item(
                TableName=self._tabla,
                Key=_claves(tenant_id=tenant_id, conversation_id=conversation_id),
            )
        except (BotoCoreError, ClientError) as exc:
            _traducir(exc, operacion="delete", tenant_id=tenant_id)
        _logger.info(
            "dynamodb.checkpoint_delete",
            extra={"tenant_id": tenant_id, "conversation_id": conversation_id},
        )
