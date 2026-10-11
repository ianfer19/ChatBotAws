"""`MessageConsumer` (composition root `src/handlers/consumer.py`, Paso 9 Fase 6).

Prueban el consumer end-to-end con dobles en memoria (sin Bedrock, DynamoDB ni Meta):
lee el historial, invoca al supervisor, envía la respuesta por el canal, persiste el
turno, acusa `batchItemFailures` para mensajes inválidos o fallidos y no envía nada
cuando el supervisor solo enrutó sin redactar.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from handlers.consumer import MessageConsumer, _LectorContextoVacio, main
from shared.contracts.messages import (
    CustomerContext,
    OutboundMessage,
    QueuedMessage,
)
from shared.contracts.types import Channel
from shared.errors import ToolError, ValidationError
from shared.ports import ChannelMessage, ChannelPort, LLMMessage

TENANT = "Sede_Elite_01"
CORRELACION = "corr-1"
EMISOR = "1000"
CLIENTE = "57300111111"
CANAL = "whatsapp"
CONVERSACION = f"{CANAL}:{CLIENTE}"
MOMENTO = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def _queued(**extra: Any) -> QueuedMessage:
    """Construye un `QueuedMessage` válido con overrides para el test.

    Args:
        **extra: Campos a sobrescribir (p. ej. `text=None`).

    Returns:
        Mensaje encolado listo para el consumer.
    """
    base: dict[str, Any] = {
        "tenant_id": TENANT,
        "correlation_id": CORRELACION,
        "channel": CANAL,
        "emitter_id": EMISOR,
        "customer_id": CLIENTE,
        "message_id": "wamid.1",
        "timestamp": MOMENTO,
        "text": "hola",
        "raw_payload": '{"object":"whatsapp_business_account"}',
    }
    base.update(extra)
    return QueuedMessage.model_validate(base)


class _GrafoFalso:
    """Doble del grafo del supervisor: devuelve la respuesta fijada y registra la entrada."""

    def __init__(self, reply: str | None = "buenas", routed: Any = None) -> None:
        """Fija la respuesta o el enrutado que devolverá `invoke`.

        Args:
            reply: Texto de respuesta; `None` simula un turno solo enrutado.
            routed: Valor de `routed` cuando no hay `reply` (p. ej. un `RoutedTurn`).
        """
        self._reply = reply
        self._routed = routed
        self.invocations: list[dict[str, Any]] = []
        self.falla: Exception | None = None

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Registra el estado recibido y devuelve la respuesta configurada.

        Args:
            state: Estado inicial (`message` + `history`).

        Returns:
            Dict final con `reply` y/o `routed`.

        Raises:
            Exception: La falla inyectada por el test (simula Bedrock caído).
        """
        if self.falla is not None:
            raise self.falla
        self.invocations.append(state)
        salida: dict[str, Any] = {}
        if self._reply is not None:
            salida["reply"] = self._reply
        if self._routed is not None:
            salida["routed"] = self._routed
        return salida


class _ConversationsFalso:
    """Doble de `DynamoConversationStore`: historial fijado y turnos registrados."""

    def __init__(self, historial: list[LLMMessage] | None = None) -> None:
        """Fija el historial que devolverá y empieza sin turnos persistidos.

        Args:
            historial: Ventana a devolver; `None` = conversación nueva.
        """
        self._historial = historial or []
        self.persistidos: list[dict[str, Any]] = []
        self.falla: Exception | None = None

    def historial(self, *, tenant_id: str, conversation_id: str, ventana: int) -> list[LLMMessage]:
        """Devuelve el historial fijado (o falla si el test lo pidió).

        Args:
            tenant_id: Comercio consultado.
            conversation_id: Conversación consultada.
            ventana: Tamaño pedido por el consumer.

        Returns:
            Lista de `LLMMessage` fijada en el constructor.

        Raises:
            Exception: La falla inyectada por el test.
        """
        if self.falla is not None:
            raise self.falla
        return list(self._historial)

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
        """Registra el turno persistido por el consumer.

        Args:
            tenant_id: Comercio dueño del turno.
            conversation_id: Conversación del turno.
            correlation_id: Correlación del turno.
            texto_usuario: Texto del cliente.
            texto_asistente: Respuesta del asistente.
            momento: Marca temporal del turno.
        """
        self.persistidos.append(
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "correlation_id": correlation_id,
                "texto_usuario": texto_usuario,
                "texto_asistente": texto_asistente,
                "momento": momento,
            }
        )


class _ChannelFalso:
    """Doble de `ChannelPort`: captura lo enviado y puede fingir un fallo."""

    def __init__(self) -> None:
        """Prepara el doble sin envíos."""
        self.sent: list[OutboundMessage] = []
        self.falla: Exception | None = None

    def send(self, message: OutboundMessage) -> None:
        """Captura la respuesta saliente (o falla si el test lo pidió).

        Args:
            message: Mensaje saliente hacia el canal.

        Raises:
            Exception: La falla inyectada por el test (simula Meta caído).
        """
        if self.falla is not None:
            raise self.falla
        self.sent.append(message)

    def normalize_inbound(
        self, payload: Mapping[str, object], *, channel: Channel
    ) -> list[ChannelMessage]:
        """No usado por el consumer (solo envía): devuelve lista vacía.

        Args:
            payload: Payload crudo del canal (ignorado).
            channel: Canal detectado (ignorado).

        Returns:
            Lista vacía (el consumer no normaliza entrada).
        """
        return []

    def verify_credentials(self, *, channel: Channel, tenant_id: str) -> bool:
        """No usado por el consumer (solo envía): devuelve `True`.

        Args:
            channel: Canal consultado (ignorado).
            tenant_id: Comercio consultado (ignorado).

        Returns:
            `True` (el doble siempre «tiene credenciales»).
        """
        return True


def _consumer(
    *,
    grafo: _GrafoFalso | None = None,
    conversations: _ConversationsFalso | None = None,
    channel: _ChannelFalso | None = None,
    ventana: int = 10,
) -> tuple[MessageConsumer, _GrafoFalso, _ConversationsFalso, _ChannelFalso]:
    """Compone un consumer con los tres dobles (creando los que falten).

    Returns:
        Tupla `(consumer, grafo, conversations, channel)` para asertar sobre los dobles.
    """
    g = grafo or _GrafoFalso()
    c = conversations or _ConversationsFalso()
    ch = channel or _ChannelFalso()
    return (
        MessageConsumer(grafo=g, conversations=c, channel=ch, ventana=ventana),
        g,
        c,
        ch,
    )


def _registro(message_id: str, payload: QueuedMessage) -> dict[str, Any]:
    """Envuelve un `QueuedMessage` en el formato del evento SQS real.

    Args:
        message_id: Id del mensaje en SQS.
        payload: Mensaje ya tipado.

    Returns:
        Dict `{"messageId":..., "body": ...}` como lo entrega SQS.
    """
    return {
        "messageId": message_id,
        "body": json.dumps(
            {"event": "inbound.message", "payload": payload.model_dump(mode="json")}
        ),
    }


def test_process_message_envia_la_respuesta_y_persiste_el_turno() -> None:
    """Camino feliz: historial → supervisor → canal, y el turno queda persistido."""
    consumer, grafo, conversations, channel = _consumer(
        conversations=_ConversationsFalso(
            [LLMMessage(role="user", content="antes"), LLMMessage(role="assistant", content="ok")]
        )
    )
    consumer.process_message(_queued())
    assert len(channel.sent) == 1
    enviado = channel.sent[0]
    assert enviado.tenant_id == TENANT
    assert enviado.emitter_id == EMISOR
    assert enviado.customer_id == CLIENTE
    assert enviado.text == "buenas"
    # El grafo recibió la ventana leída y el mensaje tipado.
    assert grafo.invocations[0]["history"] == [
        LLMMessage(role="user", content="antes"),
        LLMMessage(role="assistant", content="ok"),
    ]
    assert grafo.invocations[0]["message"].tenant_id == TENANT
    # El turno se persistió con la respuesta y la conversación compuesta.
    assert len(conversations.persistidos) == 1
    persistido = conversations.persistidos[0]
    assert persistido["conversation_id"] == CONVERSACION
    assert persistido["texto_usuario"] == "hola"
    assert persistido["texto_asistente"] == "buenas"


def test_process_message_sin_reply_no_envia_nada_pero_persiste() -> None:
    """Un turno solo enrutado (sin `reply`) no envía nada al canal y se acusa en log."""
    consumer, _grafo, conversations, channel = _consumer(grafo=_GrafoFalso(reply=None))
    consumer.process_message(_queued())
    assert channel.sent == []
    assert conversations.persistidos[0]["texto_asistente"] == "(sin respuesta)"


def test_process_message_sin_texto_falla() -> None:
    """Un mensaje sin texto no se procesa (el supervisor lo rechazaría igual)."""
    consumer, _grafo, _conversations, channel = _consumer()
    with pytest.raises(ValidationError):
        consumer.process_message(_queued(text=None))
    assert channel.sent == []


def test_process_batch_acepta_lote_valido_sin_fallos() -> None:
    """Un lote con mensajes válidos devuelve `batchItemFailures` vacío."""
    consumer, _grafo, _conversations, _channel = _consumer()
    event = {"Records": [_registro("sqs-1", _queued()), _registro("sqs-2", _queued())]}
    assert consumer.process_batch(event) == []


def test_process_batch_acusa_los_mensajes_invalidos() -> None:
    """Un payload que no valida el contrato se acusa para reintento, sin romper el lote."""
    consumer, _grafo, _conversations, _channel = _consumer()
    malo = {"messageId": "sqs-bad", "body": json.dumps({"event": "inbound.message", "payload": {}})}
    bueno = _registro("sqs-ok", _queued())
    fallos = consumer.process_batch({"Records": [malo, bueno]})
    assert fallos == [{"itemIdentifier": "sqs-bad"}]


def test_process_batch_acusa_los_mensajes_fallidos_y_sigue() -> None:
    """Si un mensaje falla (Bedrock/Meta caído), se acusa y el resto del lote sigue."""
    grafo = _GrafoFalso()
    consumer, _g, _c, _ch = _consumer(grafo=grafo)
    grafo.falla = ToolError("bedrock caido", details={"tenant_id": TENANT})
    fallos = consumer.process_batch({"Records": [_registro("sqs-1", _queued())]})
    assert fallos == [{"itemIdentifier": "sqs-1"}]


def test_main_consumer_inyectado_devuelve_batch_item_failures() -> None:
    """`main` (entrada Lambda) delega en el consumer inyectado y devuelve el dict SQS."""
    consumer, _grafo, _conversations, _channel = _consumer()
    event = {"Records": [_registro("sqs-1", _queued())]}
    salida = main(event, None, consumer=consumer)
    assert salida == {"batchItemFailures": []}


def test_lector_contexto_vacio_devuelve_contexto_valido() -> None:
    """El lector vacío cumple el `ContextReaderPort`: contexto solo con identificadores."""
    lector = _LectorContextoVacio()
    contexto = lector.get_customer_context(tenant_id=TENANT, customer_id=CLIENTE)
    assert isinstance(contexto, CustomerContext)
    assert contexto.tenant_id == TENANT
    assert contexto.customer_id == CLIENTE


def test_channel_doble_satisface_el_port() -> None:
    """El doble de canal cumple `ChannelPort` (la composición real lo usa como tal)."""
    channel: ChannelPort = _ChannelFalso()
    assert isinstance(channel, ChannelPort)
