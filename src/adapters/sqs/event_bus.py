"""Adapter de SQS tras `EventBusPort`: cola de entrada al consumer (Paso 9).

Cuerpo del mensaje: `{"event": <nombre>, "payload": <contrato ya validado>}`; el
consumer despacha por `event` y nunca loguea el payload (lleva PII), solo el nombre
y el `MessageId` que devuelve SQS.
"""

import json
from collections.abc import Mapping
from typing import Any, Protocol, cast, runtime_checkable

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

logger = get_logger(__name__)

_SQS_SERVICE = "sqs"


@runtime_checkable
class ColaSQS(Protocol):
    """Subconjunto de `sqs` que usa este adapter (DI y dobles de test)."""

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        """Publica un mensaje en la cola.

        Args:
            QueueUrl: URL completa de la cola destino.
            MessageBody: Cuerpo JSON del evento (ya serializado).

        Returns:
            Respuesta con el `MessageId` asignado por SQS.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


def _cliente_real(timeout_seconds: int) -> ColaSQS:
    """Crea el cliente `sqs` con timeout y reintentos limitados.

    Args:
        timeout_seconds: Segundos de espera de conexión y de envío.

    Returns:
        Cliente listo para `send_message`.

    TODO(verify): número de reintentos y parámetros de `Config`, verificados
    contra la doc de botocore (mismo criterio que `DynamoDBMemoryStore`).
    """
    config = Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    # boto3 no tiene stubs: la anotación es la que garantiza la firma del protocolo.
    cliente: ColaSQS = boto3.client(_SQS_SERVICE, config=config)
    return cliente


class SQSEventBus:
    """`EventBusPort` sobre una cola SQS (con DLQ detrás, ver `infra/modules/sqs`).

    Args:
        queue_url: URL de la cola de entrada (`CHATBOT_EVENTS_QUEUE_URL`).
        timeout_seconds: Timeout de conexión y de envío.
        client: Cliente inyectable (doble de test); `None` crea el real con boto3.

    Raises:
        ValidationError: Si `queue_url` está vacío (fail fast de composición).

    Example:
        >>> from adapters.sqs import SQSEventBus
        >>> from unittest.mock import MagicMock
        >>> cliente = MagicMock()
        >>> cola = SQSEventBus(queue_url="https://sqs/cola", client=cliente)
        >>> cola.publish("inbound.message", {"tenant_id": "Sede_Elite_01"})
        >>> cliente.send_message.call_args.kwargs["QueueUrl"]
        'https://sqs/cola'
    """

    def __init__(
        self,
        *,
        queue_url: str,
        timeout_seconds: int = 5,
        client: ColaSQS | None = None,
    ) -> None:
        if not queue_url:
            raise ValidationError("cola de eventos vacia")
        self._queue_url = queue_url
        self._client = client if client is not None else _cliente_real(timeout_seconds)

    def publish(self, event_name: str, payload: Mapping[str, object]) -> None:
        """Publica el evento ya validado por su contrato en `shared/contracts`.

        Args:
            event_name: Nombre estable del evento (`inbound.message`).
            payload: Datos serializables a JSON (el llamador ya pasó por Pydantic).

        Returns:
            None; el éxito se loguea con el nombre del evento, nunca con el
            payload (contiene PII del cliente).

        Raises:
            ToolError: Si el payload no es JSON o SQS rechaza el envío (el
                original va en `__cause__`; el webhook libera la deduplicación).
            ToolTimeoutError: Si el envío excede el timeout.
        """
        try:
            cuerpo = json.dumps({"event": event_name, "payload": dict(payload)}, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ToolError(
                "payload del evento no serializable",
                details={"event_name": event_name},
            ) from exc
        try:
            respuesta = self._client.send_message(QueueUrl=self._queue_url, MessageBody=cuerpo)
        except (ConnectTimeoutError, ReadTimeoutError) as exc:
            raise ToolTimeoutError(
                "timeout de sqs al encolar el evento",
                details={"event_name": event_name},
            ) from exc
        except (BotoCoreError, ClientError) as exc:
            raise ToolError(
                "sqs rechazo el evento",
                details={"event_name": event_name, "codigo": _codigo(exc)},
            ) from exc
        logger.info(
            "sqs.evento_encolado",
            extra={"event_name": event_name, "message_id": str(respuesta.get("MessageId", ""))},
        )


def _codigo(exc: Exception) -> str:
    """Extrae el código de error de botocore para el log/`details`.

    Args:
        exc: Excepción capturada del cliente.

    Returns:
        El código SQS/de servicio, o `desconocido`.
    """
    if isinstance(exc, ClientError):
        # `cast` explícito: el estrechamiento del isinstance no siempre lo capta
        # el chequeo estático alternativo (pyrefly), y el tipo es inequívoco aquí.
        error = cast(ClientError, exc)
        return str(error.response.get("Error", {}).get("Code", "desconocido"))
    return type(exc).__name__
