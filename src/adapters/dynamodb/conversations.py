"""Adapter de DynamoDB para la tabla `chatbot_conversations` (Paso 9, Fase 6).

Persiste el turno entrante y la respuesta del pipeline como dos ítems por mensaje y
recupera la ventana de historial más reciente como `LLMMessage[]` que el supervisor
exige en cada turno (requisito 7.2, ADR 0013). Réplica de las claves de DATA_MODEL
(`ORG#<tenant>` + `CONV#<conversation>` + `MSG#<conversation>#<tsISO>`) con TTL por
mensaje, particionada siempre por `tenant_id`: un cliente de un comercio jamás se lee
desde otro. El texto completo se guarda para poder reconstruir el historial; los
metadatos de media no viajan al LLM (solo texto).

Errores: `ClientError`/`BotoCoreError` se traducen a `ToolError` y los timeouts a
`ToolTimeoutError`; jamás se fuga `botocore` al dominio. Los clientes son inyectables
para testear sin AWS.
"""

import time
from collections.abc import Mapping
from datetime import datetime
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
from shared.ports import LLMMessage

logger = get_logger(__name__)

_TTL_CONVERSACION_SEGUNDOS = 30 * 24 * 60 * 60
# Ventana de mensajes que se devuelve al supervisor; lo que desborda se resume en el
# nodo `window_history` (Paso 8), que recorta de nuevo con `history_window_size`.
_DEFAULT_VENTANA = 10


@runtime_checkable
class TablaConversaciones(Protocol):
    """Subconjunto de `Table` (recursos de boto3) que usa este adapter."""

    name: str

    def put_item(self, *, Item: Mapping[str, Any]) -> dict[str, Any]:
        """Escribe (o sobrescribe) un ítem de conversación.

        Args:
            Item: Atributos del ítem (`PK`, `SK`, `role`, `text`, `correlation_id`, `ttl`).

        Returns:
            Respuesta de DynamoDB.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...

    def query(
        self,
        *,
        TableName: str,
        KeyConditionExpression: str,
        ExpressionAttributeValues: Mapping[str, Any],
        ScanIndexForward: bool = ...,
        Limit: int = ...,
    ) -> dict[str, Any]:
        """Consulta los ítems de una partición ordenados por `SK`.

        Args:
            TableName: Nombre real de la tabla.
            KeyConditionExpression: Condición de clave (`PK = :pk AND begins_with(SK, :sk)`).
            ExpressionAttributeValues: Valores de los placeholders.
            ScanIndexForward: `True` = orden ascendente por `SK` (cronológico).
            Limit: Máximo de ítems a devolver.

        Returns:
            Diccionario con `Items`.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


def _tabla_real(table_name: str, timeout_seconds: int) -> TablaConversaciones:
    """Crea la `Table` real de boto3 con timeout y reintentos limitados.

    Args:
        table_name: Nombre real de la tabla (`chatbot_conversations_<ambiente>`).
        timeout_seconds: Segundos de espera de conexión y de operación.

    Returns:
        La tabla lista para `put_item`/`query`.

    TODO(verify): número de reintentos y parámetros de `Config`, verificados contra
    la doc de botocore (mismo criterio que `DynamoDBMemoryStore`).
    """
    config = Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    recurso = boto3.resource("dynamodb", config=config)
    tabla: TablaConversaciones = recurso.Table(table_name)
    return tabla


def _traducir(exc: Exception, *, operacion: str, tenant_id: str) -> NoReturn:
    """Traduce una excepción de botocore al error tipado del sistema.

    Args:
        exc: Excepción original capturada del cliente.
        operacion: Nombre de la operación (`persistir`, `historial`).
        tenant_id: Comercio, para el log estructurado.

    Raises:
        ToolTimeoutError: Si fue un timeout de conexión o de operación.
        ToolError: Para cualquier otro fallo de red o de negocio (el original va
            en `__cause__`, jamás se filtra al usuario final).
    """
    if isinstance(exc, ConnectTimeoutError | ReadTimeoutError):
        raise ToolTimeoutError(
            "timeout de dynamodb en conversaciones",
            details={"operacion": operacion, "tenant_id": tenant_id},
        ) from exc
    if isinstance(exc, ClientError):
        error = cast(ClientError, exc)
        codigo = str(error.response.get("Error", {}).get("Code", "desconocido"))
        raise ToolError(
            "dynamodb rechazo la operacion de conversaciones",
            details={"operacion": operacion, "tenant_id": tenant_id, "codigo": codigo},
        ) from exc
    raise ToolError(
        "dynamodb no respondio en conversaciones",
        details={"operacion": operacion, "tenant_id": tenant_id},
    ) from exc


class DynamoConversationStore:
    """`chatbot_conversations`: persiste turnos y devuelve la ventana de historial.

    El historial es **la fuente de verdad de la ventana** (decisión de la Fase 6): en
    lugar de depender del checkpointer de LangGraph para reconstruir el pasado, el
    consumer lee los últimos mensajes de esta tabla y se los pasa al supervisor como
    `history`. Cada turno añade dos ítems (`user` + `assistant`) con su `SK` ordenable
    por timestamp, de modo que la consulta ascendente limitada a `ventana` devuelve la
    conversación en orden cronológico. `TODO(decision)`: ¿mismo almacén para el
    checkpointer de LangGraph (Paso 8) o tablas separadas? Hoy están separadas.

    Args:
        table_name: Nombre real de la tabla (`chatbot_conversations_<ambiente>`).
        ttl_seconds: Caducidad de cada mensaje; por defecto 30 días (retención de
            conversaciones: ADR 0007, fuera de la ruta pero no olvidada).
        timeout_seconds: Timeout del cliente.
        ventana: Máximo de mensajes que devuelve `historial` (la ventana que ve el
            clasificador; `window_history` puede recortar aún más).
        table: Tabla inyectable (doble de test); `None` crea la real con boto3.

    Raises:
        ValidationError: Si `table_name` está vacío o la ventana es < 1.
    """

    def __init__(
        self,
        *,
        table_name: str,
        ttl_seconds: int = _TTL_CONVERSACION_SEGUNDOS,
        timeout_seconds: int = 5,
        ventana: int = _DEFAULT_VENTANA,
        table: TablaConversaciones | None = None,
    ) -> None:
        if not table_name:
            raise ValidationError("nombre de tabla de conversaciones vacio")
        if ventana < 1:
            raise ValidationError("ventana de conversaciones debe ser >= 1")
        if ttl_seconds < 0:
            raise ValidationError("ttl de conversaciones negativo")
        self._tabla = table if table is not None else _tabla_real(table_name, timeout_seconds)
        self._ttl_seconds = ttl_seconds
        self._ventana = ventana

    def persistir_turno(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        correlation_id: str,
        texto_usuario: str,
        texto_asistente: str,
        momento: datetime,
    ) -> None:
        """Guarda el turno completo (usuario + respuesta) como dos ítems ordenables.

        El `SK` es `MSG#<conversation_id>#<tsISO>` para que la consulta por partición
        devuelva los mensajes en orden cronológico sin un GSI (DATA_MODEL §DynamoDB).

        Args:
            tenant_id: Comercio dueño de la conversación (forma parte de la clave).
            conversation_id: Identificador de la conversación (`<channel>:<cliente>`).
            correlation_id: Correlación del turno, para trazarlo en logs.
            texto_usuario: Texto enviado por el cliente.
            texto_asistente: Respuesta ya redactada por el pipeline.
            momento: Marca temporal del turno (UTC; la aporta el reloj del consumer).

        Returns:
            None; ambos ítems se escriben con el mismo TTL.

        Raises:
            ValidationError: Si falta alguno de los campos obligatorios.
            ToolError: Si DynamoDB rechaza la escritura o falla la red.
            ToolTimeoutError: Si la escritura excede el timeout.
        """
        if not tenant_id or not conversation_id or not correlation_id:
            raise ValidationError("faltan tenant_id, conversation_id o correlation_id")
        if not texto_usuario or not texto_asistente:
            raise ValidationError("turno sin texto de usuario o de asistente")
        ahora = int(time.time())
        ttl = ahora + self._ttl_seconds
        iso = momento.isoformat()
        prefijo = f"ORG#{tenant_id}"
        for rol, texto in (("user", texto_usuario), ("assistant", texto_asistente)):
            item = {
                "PK": prefijo,
                "SK": f"MSG#{conversation_id}#{iso}#{rol}",
                "conversation_id": conversation_id,
                "role": rol,
                "text": texto,
                "correlation_id": correlation_id,
                "ttl": ttl,
            }
            try:
                self._tabla.put_item(Item=item)
            except (BotoCoreError, ClientError) as exc:
                _traducir(exc, operacion="persistir", tenant_id=tenant_id)
        logger.info(
            "dynamodb.conversacion_persistida",
            extra={"tenant_id": tenant_id, "conversation_id": conversation_id},
        )

    def historial(
        self, *, tenant_id: str, conversation_id: str, ventana: int | None = None
    ) -> list[LLMMessage]:
        """Devuelve la ventana de historial más reciente como `LLMMessage[]`.

        La ventana es lo que el supervisor exige en cada turno (requisito 7.2). Se
        ordena ascendente por `SK` y se limita a `ventana` mensajes: el clasificador
        nunca ve más allá de esa ventana (el nodo `window_history` puede recortarla
        aún más con `history_window_size`).

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Conversación consultada.
            ventana: Tamaño de la ventana; `None` usa el del constructor.

        Returns:
            Lista de `LLMMessage` en orden cronológico (vacía si no hay historial).

        Raises:
            ValidationError: Si falta `tenant_id`/`conversation_id` o la ventana es < 1.
            ToolError: Si DynamoDB falla o un ítem tiene `role`/`text` inválidos.
            ToolTimeoutError: Si la lectura excede el timeout.
        """
        if not tenant_id or not conversation_id:
            raise ValidationError("faltan tenant_id o conversation_id en el historial")
        limite = self._ventana if ventana is None else ventana
        if limite < 1:
            raise ValidationError("ventana de historial debe ser >= 1")
        try:
            valores = {":pk": f"ORG#{tenant_id}", ":sk": f"MSG#{conversation_id}#"}
            respuesta = self._tabla.query(
                TableName=self._tabla.name,
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
                ExpressionAttributeValues=valores,
                ScanIndexForward=True,
                Limit=limite * 2,
            )
        except (BotoCoreError, ClientError) as exc:
            _traducir(exc, operacion="historial", tenant_id=tenant_id)
        mensajes: list[LLMMessage] = []
        for item in respuesta.get("Items", []):
            rol = item.get("role")
            texto = item.get("text")
            if rol not in ("user", "assistant") or not isinstance(texto, str) or not texto:
                raise ToolError(
                    "item de conversacion con role o text invalidos",
                    details={"tenant_id": tenant_id, "conversation_id": conversation_id},
                )
            mensajes.append(LLMMessage(role=rol, content=texto))
        # `ScanIndexForward=True` ya devuelve orden cronológico; se recorta a la
        # ventana por si la tabla devuelve ítems de más (p. ej. con TTL a medias).
        return mensajes[-limite:]
