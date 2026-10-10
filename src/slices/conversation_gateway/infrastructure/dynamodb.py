"""Adapters de DynamoDB del gateway: mapeo canal→tenant y deduplicación (Fase 4).

Replican las dos lecturas/escrituras en línea del webhook sobre la API de recursos
de boto3 (tipos nativos, sin `AttributeValue`), con timeouts, reintentos limitados
y errores traducidos: jamás se fuga un `ClientError` a la aplicación. Los clientes
son inyectables para testear sin AWS.

Claves (decisión del Paso 9, réplica del legacy):

- Mapeo: `PK = WA_CONFIG#<emitter_id>` (o `IG_CONFIG#`/`FB_CONFIG#`) + `SK = METADATA`,
  como en `whatsapp_orchestrator_service/app.py:264`; el tenant está en `store_id`.
- Dedup: `PK = MSG_PROCESSED#<message_id>` + `SK = DEDUP#<tenant_id>` con
  `attribute_not_exists(PK)` y TTL de 24 h (el legacy es `SK = DEDUP` global; aquí
  el tenant va en la clave — regla de aislamiento, MULTI_TENANCY §4).
"""

import time
from collections.abc import Mapping
from typing import Any, NoReturn, Protocol, cast, runtime_checkable

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

from shared.contracts.types import Channel
from shared.errors import TenantNotFoundError, ToolError, ToolTimeoutError, ValidationError
from shared.logging import get_logger

logger = get_logger(__name__)

_TTL_DEDUP_SEGUNDOS = 24 * 60 * 60
# Meta reintenta durante horas; 24 h de ventana cubren sus reenvíos sin acumular
# ítems (decisión 2 del checklist del Paso 9).
_SK_MAPEO = "METADATA"
_PREFIJOS: Mapping[Channel, str] = {
    "whatsapp": "WA_CONFIG",
    "instagram": "IG_CONFIG",
    "messenger": "FB_CONFIG",
}
_CODIGO_CONDICIONAL = "ConditionalCheckFailedException"


@runtime_checkable
class TablaLectura(Protocol):
    """Subconjunto de `Table` (recursos de boto3) que lee el mapeo de canal."""

    def get_item(self, *, Key: Mapping[str, str], ConsistentRead: bool = ...) -> dict[str, Any]:
        """Lee un ítem por clave.

        Args:
            Key: Clave del ítem (`PK` + `SK`).
            ConsistentRead: Lectura fuerte (el mapeo se recién crea en dev).

        Returns:
            Diccionario con `Item` si existe; vacío si no.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


@runtime_checkable
class TablaEscritura(Protocol):
    """Subconjunto de `Table` (recursos de boto3) que escribe la deduplicación."""

    def put_item(
        self, *, Item: Mapping[str, Any], ConditionExpression: str = ...
    ) -> dict[str, Any]:
        """Escribe un ítem solo si la condición se cumple.

        Args:
            Item: Atributos del ítem (`PK`, `SK`, `processed_at`, `ttl`).
            ConditionExpression: Condición atómica de reclamación.

        Returns:
            Respuesta de DynamoDB si se escribió.

        Raises:
            ClientError: `ConditionalCheckFailedException` si ya existía u otros.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...

    def delete_item(self, *, Key: Mapping[str, str]) -> dict[str, Any]:
        """Borra un ítem por clave (idempotente si no existía).

        Args:
            Key: Clave del ítem (`PK` + `SK`).

        Returns:
            Respuesta de DynamoDB.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


def _tabla_real(table_name: str, timeout_seconds: int) -> Any:
    """Crea la `Table` real de boto3 con timeout y reintentos limitados.

    Args:
        table_name: Nombre real de la tabla (`<tabla>_<ambiente>`).
        timeout_seconds: Segundos de espera de conexión y de operación.

    Returns:
        La tabla lista para `get_item`/`put_item`/`delete_item`.

    TODO(verify): número de reintentos y que `boto3.resource` acepte `Config`
    con estos timeouts, verificados contra la doc de botocore (mismo criterio que
    `DynamoDBMemoryStore`).
    """
    config = Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    recurso = boto3.resource("dynamodb", config=config)
    return recurso.Table(table_name)


def _es_condicional(exc: ClientError) -> bool:
    """Detecta el fallo de `ConditionExpression` (ítem ya reclamado).

    Args:
        exc: Excepción capturada del cliente.

    Returns:
        `True` solo para `ConditionalCheckFailedException`.
    """
    error = cast(ClientError, exc)
    return str(error.response.get("Error", {}).get("Code")) == _CODIGO_CONDICIONAL


def _traducir(exc: Exception, *, operacion: str, detalle: str) -> NoReturn:
    """Traduce una excepción de botocore al error tipado del sistema.

    Args:
        exc: Excepción original capturada del cliente.
        operacion: Nombre de la operación que falló (`mapeo`, `dedup`, `liberar`).
        detalle: Contexto no sensible (id del emisor o del mensaje).

    Raises:
        ToolTimeoutError: Si fue un timeout de conexión o de operación.
        ToolError: Para cualquier otro fallo de red o de negocio (el original va
            en `__cause__`, jamás se filtra al usuario final).
    """
    if isinstance(exc, ConnectTimeoutError | ReadTimeoutError):
        raise ToolTimeoutError(
            "timeout de dynamodb en el gateway",
            details={"operacion": operacion, "detalle": detalle},
        ) from exc
    if isinstance(exc, ClientError):
        error = cast(ClientError, exc)
        codigo = str(error.response.get("Error", {}).get("Code", "desconocido"))
        raise ToolError(
            "dynamodb rechazo la operacion del gateway",
            details={"operacion": operacion, "detalle": detalle, "codigo": codigo},
        ) from exc
    raise ToolError(
        "dynamodb no respondio en el gateway",
        details={"operacion": operacion, "detalle": detalle},
    ) from exc


class DynamoChannelMapping:
    """`TenantResolverPort` sobre la tabla `chatbot_channel_mapping` (replica del legacy).

    Args:
        table_name: Nombre real de la tabla de mapeo.
        timeout_seconds: Timeout del cliente.
        table: Tabla inyectable (doble de test); `None` crea la real con boto3.

    Raises:
        ValidationError: Si `table_name` está vacío (fail fast de composición).
    """

    def __init__(
        self,
        *,
        table_name: str,
        timeout_seconds: int = 5,
        table: TablaLectura | None = None,
    ) -> None:
        if not table_name:
            raise ValidationError("nombre de tabla de mapeo de canal vacio")
        self._tabla = table if table is not None else _tabla_real(table_name, timeout_seconds)

    def resolve(self, *, channel: Channel, emitter_id: str) -> str:
        """Devuelve el `store_id` dueño de ese emisor Meta (o `TenantNotFoundError`).

        Args:
            channel: Canal por el que llegó el webhook.
            emitter_id: Id del emisor del payload (`phone_number_id`, id de página).

        Returns:
            El `tenant_id` (store_id legado) resuelto.

        Raises:
            TenantNotFoundError: Si no hay mapeo: el evento se acusa a Meta como
                `EVENT_TENANT_UNKNOWN` sin invocar al supervisor.
            ValidationError: Si falta `emitter_id`.
            ToolError: Si DynamoDB falla o devuelve un ítem sin `store_id`.
            ToolTimeoutError: Si la lectura excede el timeout.
        """
        if not emitter_id:
            raise ValidationError("emitter_id vacio en el mapeo de canal")
        clave = {"PK": f"{_PREFIJOS[channel]}#{emitter_id}", "SK": _SK_MAPEO}
        try:
            respuesta = self._tabla.get_item(Key=clave, ConsistentRead=True)
        except (BotoCoreError, ClientError) as exc:
            _traducir(exc, operacion="mapeo", detalle=emitter_id)
        item = respuesta.get("Item") or {}
        tenant_id = item.get("store_id") or item.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise TenantNotFoundError(
                "sin mapeo de canal→tenant",
                details={"channel": channel, "emitter_id": emitter_id},
            )
        logger.info(
            "dynamodb.tenant_resuelto",
            extra={"channel": channel, "tenant_id": tenant_id},
        )
        return tenant_id


class DynamoDeduplication:
    """`DeduplicationPort` sobre la tabla `chatbot_processed_messages` (TTL 24 h).

    Args:
        table_name: Nombre real de la tabla de mensajes procesados.
        ttl_seconds: Caducidad del registro de deduplicación (24 h por defecto).
        timeout_seconds: Timeout del cliente.
        table: Tabla inyectable (doble de test); `None` crea la real con boto3.

    Raises:
        ValidationError: Si `table_name` está vacío o el TTL es negativo.
    """

    def __init__(
        self,
        *,
        table_name: str,
        ttl_seconds: int = _TTL_DEDUP_SEGUNDOS,
        timeout_seconds: int = 5,
        table: TablaEscritura | None = None,
    ) -> None:
        if not table_name:
            raise ValidationError("nombre de tabla de mensajes procesados vacio")
        if ttl_seconds < 0:
            raise ValidationError("ttl de deduplicacion negativo")
        self._tabla = table if table is not None else _tabla_real(table_name, timeout_seconds)
        self._ttl_seconds = ttl_seconds

    def register_once(self, *, tenant_id: str, message_id: str) -> bool:
        """Reclama el mensaje de forma atómica; `False` si otro intento ya lo tenía.

        Args:
            tenant_id: Comercio resuelto en el gateway.
            message_id: Id del mensaje en el canal (wamid/mid).

        Returns:
            `True` si es la primera vez; `False` si ya estaba registrado
            (`ConditionalCheckFailedException`, que no es un error de servicio).

        Raises:
            ValidationError: Si falta `tenant_id` o `message_id`.
            ToolError: Si DynamoDB falla por otro motivo.
            ToolTimeoutError: Si la escritura excede el timeout.
        """
        _validar_claves(tenant_id=tenant_id, message_id=message_id)
        ahora = int(time.time())
        item = {
            "PK": f"MSG_PROCESSED#{message_id}",
            "SK": f"DEDUP#{tenant_id}",
            "processed_at": ahora,
            "ttl": ahora + self._ttl_seconds,
        }
        try:
            self._tabla.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        except ClientError as exc:
            if _es_condicional(exc):
                return False
            _traducir(exc, operacion="dedup", detalle=message_id)
        except BotoCoreError as exc:
            _traducir(exc, operacion="dedup", detalle=message_id)
        logger.info("dynamodb.dedup_registrado", extra={"tenant_id": tenant_id})
        return True

    def release(self, *, tenant_id: str, message_id: str) -> None:
        """Borra el registro para que un encolado fallido pueda reintentarse.

        Args:
            tenant_id: Comercio resuelto en el gateway.
            message_id: Id del mensaje en el canal.

        Returns:
            None; borrar un ítem ya borrado no es error (idempotente).

        Raises:
            ValidationError: Si falta `tenant_id` o `message_id`.
            ToolError: Si DynamoDB rechaza el borrado.
            ToolTimeoutError: Si el borrado excede el timeout.
        """
        _validar_claves(tenant_id=tenant_id, message_id=message_id)
        clave = {"PK": f"MSG_PROCESSED#{message_id}", "SK": f"DEDUP#{tenant_id}"}
        try:
            self._tabla.delete_item(Key=clave)
        except (BotoCoreError, ClientError) as exc:
            _traducir(exc, operacion="liberar", detalle=message_id)
        logger.info("dynamodb.dedup_liberado", extra={"tenant_id": tenant_id})


def _validar_claves(*, tenant_id: str, message_id: str) -> None:
    """Exige los dos componentes de la clave de deduplicación.

    Args:
        tenant_id: Comercio resuelto.
        message_id: Id del mensaje en el canal.

    Raises:
        ValidationError: Si falta alguno (la clave debe llevar siempre el tenant).
    """
    if not tenant_id or not message_id:
        raise ValidationError("faltan tenant_id o message_id en la deduplicacion")
