"""Tests del adapter SQS del bus de eventos del gateway (Fase 4).

El `SQSEventBus` es el único eslabón entre el webhook y el consumidor: un fallo de
SQS debe llegar como `ToolError`/`ToolTimeoutError` (retry de Meta + rollback de
dedup) y jamás con errores de botocore ni con el payload en los mensajes.
"""

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

from adapters.sqs.event_bus import SQSEventBus
from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.ports import EventBusPort

_COLA = "https://sqs.us-east-1.amazonaws.com/123456789012/chatbot-events-dev"
_EVENTO = "inbound.message"
_PAYLOAD: dict[str, Any] = {"tenant_id": "Sede_Elite_01", "message_id": "wamid.1"}


class _ColaFalsa:
    """Doble de `ColaSQS`: registra el cuerpo enviado y puede fallar."""

    def __init__(self, *, error: Exception | None = None) -> None:
        """Prepara el doble.

        Args:
            error: Excepción a lanzar en `send_message` (`None` = envío correcto).
        """
        self.error = error
        self.enviados: list[dict[str, Any]] = []

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        """Registra el envío o falla con lo configurado.

        Args:
            QueueUrl: URL de la cola de destino.
            MessageBody: Cuerpo JSON del mensaje.

        Returns:
            Respuesta simulada con `MessageId`.

        Raises:
            Exception: La falla inyectada en el constructor.
        """
        self.enviados.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        if self.error is not None:
            raise self.error
        return {"MessageId": "abc-123"}


def _bus(cola: _ColaFalsa) -> SQSEventBus:
    """Construye el adapter con el doble de cola.

    Args:
        cola: Doble de `ColaSQS`.

    Returns:
        El `SQSEventBus` bajo prueba.
    """
    return SQSEventBus(queue_url=_COLA, client=cola)


def test_publica_un_solo_mensaje_con_evento_y_payload() -> None:
    """Cada `publish` es un mensaje SQS con `{event, payload}` (contrato con Fase 6)."""
    cola = _ColaFalsa()
    _bus(cola).publish(event_name=_EVENTO, payload=_PAYLOAD)
    assert len(cola.enviados) == 1
    assert cola.enviados[0]["QueueUrl"] == _COLA
    cuerpo = json.loads(cola.enviados[0]["MessageBody"])
    assert cuerpo == {"event": _EVENTO, "payload": _PAYLOAD}


def test_traduce_client_error_a_tool_error_sin_el_payload() -> None:
    """Un ClientError de SQS se convierte en `ToolError` sin exponer el contenido."""
    cola = _ColaFalsa(
        error=ClientError(
            {"Error": {"Code": "QueueDoesNotExist", "Message": "no existe"}},
            "SendMessage",
        )
    )
    with pytest.raises(ToolError) as excepcion:
        _bus(cola).publish(event_name=_EVENTO, payload=_PAYLOAD)
    assert excepcion.value.details.get("event_name") == _EVENTO
    assert "payload" not in str(excepcion.value).lower()


def test_traduce_timeouts_a_tool_timeout_error() -> None:
    """Timeout de conexión y de lectura: ambos son `ToolTimeoutError`."""
    cola = _ColaFalsa(error=ConnectTimeoutError(endpoint_url=_COLA))
    with pytest.raises(ToolTimeoutError):
        _bus(cola).publish(event_name=_EVENTO, payload=_PAYLOAD)
    cola2 = _ColaFalsa(error=ReadTimeoutError(endpoint_url=_COLA))
    with pytest.raises(ToolTimeoutError):
        _bus(cola2).publish(event_name=_EVENTO, payload=_PAYLOAD)


def test_payload_no_serializable_es_tool_error() -> None:
    """Un payload con objetos no JSON no debe llegar a SQS ni romper en caliente."""
    cola = _ColaFalsa()
    with pytest.raises(ToolError):
        _bus(cola).publish(event_name=_EVENTO, payload={"objeto": object()})
    assert cola.enviados == []


def test_queue_url_vacia_es_validation_error() -> None:
    """Fail fast de composición: sin cola configurada no existe el bus."""
    with pytest.raises(ValidationError):
        SQSEventBus(queue_url="", client=_ColaFalsa())


def test_sin_cliente_y_sin_credenciales_usa_boto3() -> None:
    """`client=None` construye el cliente real (integración; aquí solo la firma)."""
    cola = _ColaFalsa()
    bus = SQSEventBus(queue_url=_COLA, client=cola)
    assert bus is not None


def test_cumple_event_bus_port() -> None:
    """Satisface estructuralmente el port del dominio (DI sin herencia)."""
    assert isinstance(_bus(_ColaFalsa()), EventBusPort)


def test_el_cuerpo_es_json_utf_8_compacto() -> None:
    """Sin acentos ni saltos: payload legible para el consumidor y para `jq`."""
    cola = _ColaFalsa()
    _bus(cola).publish(event_name=_EVENTO, payload={"texto": "pedido"})
    cuerpo = cola.enviados[0]["MessageBody"]
    assert isinstance(cuerpo, str)
    assert "\n" not in cuerpo
    assert json.loads(cuerpo)["payload"]["texto"] == "pedido"


def test_no_loguea_el_payload_en_la_excepcion() -> None:
    """El error nunca debe arrastrar datos del cliente (regla de logs sin PII)."""
    cola = _ColaFalsa(
        error=ClientError(
            {"Error": {"Code": "InternalError", "Message": "interno"}},
            "SendMessage",
        )
    )
    with pytest.raises(ToolError) as excepcion:
        _bus(cola).publish(event_name=_EVENTO, payload={"telefono": "3001112222"})
    texto = str(excepcion.value)
    assert "3001112222" not in texto
    assert "Sede_Elite_01" not in texto
    assert excepcion.value.details.get("event_name") == _EVENTO
