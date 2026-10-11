"""Composition root del consumer end-to-end (Paso 9, Fase 6).

Único punto de producción que **importa varios slices** a la vez: recibe un lote de
mensajes SQS (`{"event": "inbound.message", "payload": <QueuedMessage>}`), para cada
mensaje (1) lee la ventana de historial desde `chatbot_conversations`, (2) invoca al
`supervisor` con esa ventana y con un contexto de cliente vacío (los especialistas y el
contexto real llegan en el Commit C), (3) redacta la respuesta (saludo/respuesta
directa) y (4) la envía por el canal (`MetaChannel.send`). Si el supervisor no produjo
respuesta (`routed` sin `reply`), el turno se acusa como enrutado y no se envía nada.

Es el espejo productivo de `scripts/chat_citas.py` (mismo patrón de composición), pero
sobre adaptadores reales. `src/handlers/` es el único lugar del repo que puede importar
varios slices a la vez; el test de aislamiento AST (`test_repo_contract.py`) solo cubre
`src/slices/`, y `import-linter` se registra el contenedor `handlers` con este commit.
La persistencia del turno se hace al final de cada mensaje procesado.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError as SchemaValidationError

from adapters.bedrock import BedrockLLM
from adapters.dynamodb import DynamoConversationStore
from shared.config import Settings, load_settings
from shared.contracts.messages import CustomerContext, OutboundMessage, QueuedMessage
from shared.errors import AppError, ToolError, ValidationError
from shared.logging import configure_logging, get_logger
from shared.ports import ChannelPort, LLMMessage
from slices.conversation_gateway.infrastructure.channels.http_client import RequestsGraphClient
from slices.conversation_gateway.infrastructure.channels.meta import MetaChannel
from slices.conversation_gateway.infrastructure.ssm import SsmCredentialStore
from slices.supervisor.application.graph import build_supervisor_graph

logger = get_logger(__name__)


class ConversationsPort(Protocol):
    """Subconjunto de `DynamoConversationStore` que usa el consumer (DI y dobles)."""

    def historial(self, *, tenant_id: str, conversation_id: str, ventana: int) -> list[LLMMessage]:
        """Devuelve la ventana de historial de la conversación.

        Args:
            tenant_id: Comercio dueño de la conversación.
            conversation_id: Conversación consultada.
            ventana: Tamaño de la ventana.

        Returns:
            Lista de `LLMMessage` en orden cronológico (vacía si no hay historial).
        """
        ...

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
        """Persiste el turno completo (usuario + respuesta).

        Args:
            tenant_id: Comercio dueño del turno.
            conversation_id: Conversación del turno.
            correlation_id: Correlación del turno.
            texto_usuario: Texto del cliente.
            texto_asistente: Respuesta del asistente.
            momento: Marca temporal del turno.
        """
        ...


class _LectorContextoVacio:
    """`ContextReaderPort` que siempre devuelve contexto vacío (Commit B).

    El adapter DynamoDB del contexto y los especialistas no están cableados todavía
    (Commit C); el supervisor exige un contexto por turno (requisito 7.2), así que el
    consumer le entrega un contexto vacío en lugar de omitirlo. `TODO(decision)`:
    sustituir por el adapter real de `chatbot_customer_context` en el Commit C.
    """

    def get_customer_context(self, *, tenant_id: str, customer_id: str) -> CustomerContext:
        """Devuelve un `CustomerContext` vacío para el cliente indicado.

        Args:
            tenant_id: Comercio del turno (del contexto resuelto en el gateway).
            customer_id: Cliente del turno.

        Returns:
            `CustomerContext` con solo los identificadores (defaults).
        """
        return CustomerContext(tenant_id=tenant_id, customer_id=customer_id)


class MessageConsumer:
    """Procesa un lote de mensajes SQS: historial → supervisor → envío al canal.

    Args:
        grafo: Grafo del supervisor ya compilado (`build_supervisor_graph`).
        conversations: Store de `chatbot_conversations` (lee y persiste el historial).
        channel: `ChannelPort` para enviar la respuesta (`MetaChannel` de envío).
        ventana: Tamaño de la ventana de historial que se lee por turno.

    Example:
        >>> MessageConsumer(grafo=None, conversations=None, channel=None).ventana
        10
    """

    def __init__(
        self,
        *,
        grafo: Any,
        conversations: ConversationsPort,
        channel: ChannelPort,
        ventana: int = 10,
    ) -> None:
        """Guarda las dependencias ya compuestas.

        Args:
            grafo: Grafo del supervisor compilado.
            conversations: Store de conversaciones.
            channel: Canal de envío.
            ventana: Tamaño de la ventana de historial.
        """
        self._grafo = grafo
        self._conversations = conversations
        self._channel = channel
        self._ventana = ventana

    def process_batch(self, event: Mapping[str, Any]) -> list[dict[str, str]]:
        """Procesa cada registro del lote y acumula los que deben reintentarse.

        Args:
            event: Evento SQS completo (`Records`).

        Returns:
            Lista de `{"itemIdentifier": <messageId>}` para los fallos (reintento
            por parte de la cola); vacía si todo el lote procesó sin error.
        """
        fallos: list[dict[str, str]] = []
        registros: Sequence[Mapping[str, Any]] = event.get("Records") or []
        for registro in registros:
            message_id = str(registro.get("messageId") or "")
            try:
                cuerpo = json.loads(str(registro.get("body") or "{}"))
                payload = cuerpo.get("payload") or {}
                queued = QueuedMessage.model_validate(payload)
                self.process_message(queued)
            except (
                json.JSONDecodeError,
                SchemaValidationError,
                ValidationError,
                AppError,
                ToolError,
            ) as exc:
                codigo = exc.code if isinstance(exc, AppError) else "invalid_message"
                logger.warning(
                    "consumer.message_failed",
                    extra={"message_id": message_id, "error": codigo},
                )
                fallos.append({"itemIdentifier": message_id})
        return fallos

    def process_message(self, queued: QueuedMessage) -> None:
        """Procesa un único mensaje: lee historial, invoca al supervisor y envía.

        Args:
            queued: Mensaje ya validado del contrato `QueuedMessage`.

        Returns:
            None; persiste el turno al final si todo salió bien.

        Raises:
            ToolError: Si el supervisor o el envío fallan (reintento del lote).
            ValidationError: Si el mensaje no tiene texto (no se procesa).
        """
        if not queued.text:
            raise ValidationError(
                "mensaje sin texto en el consumer",
                details={"correlation_id": queued.correlation_id},
            )
        conversation_id = f"{queued.channel}:{queued.customer_id}"
        historial = self._conversations.historial(
            tenant_id=queued.tenant_id, conversation_id=conversation_id, ventana=self._ventana
        )
        resultado = self._grafo.invoke({"message": queued, "history": list(historial)})
        reply = resultado.get("reply")
        if isinstance(reply, str) and reply:
            self._channel.send(
                OutboundMessage(
                    tenant_id=queued.tenant_id,
                    correlation_id=queued.correlation_id,
                    channel=queued.channel,
                    emitter_id=queued.emitter_id,
                    customer_id=queued.customer_id,
                    text=reply,
                )
            )
        else:
            routed = resultado.get("routed")
            destino = getattr(routed, "target", "desconocido") if routed is not None else "ninguno"
            logger.info(
                "consumer.routed_without_reply",
                extra={
                    "tenant_id": queued.tenant_id,
                    "correlation_id": queued.correlation_id,
                    "target": str(destino),
                },
            )
        self._conversations.persistir_turno(
            tenant_id=queued.tenant_id,
            conversation_id=conversation_id,
            correlation_id=queued.correlation_id,
            texto_usuario=queued.text or "",
            texto_asistente=reply if isinstance(reply, str) and reply else "(sin respuesta)",
            momento=datetime.now(UTC),
        )


def main(
    event: dict[str, Any],
    _context: Any,
    consumer: MessageConsumer | None = None,
) -> dict[str, Any]:
    """Entrada Lambda del consumer SQS: procesa el lote y devuelve `batchItemFailures`.

    Args:
        event: Evento de SQS (`Records`: `body` con JSON `{event, payload}`).
        _context: Contexto de Lambda (no usado: la composición es síncrona).
        consumer: Consumer ya compuesto; `None` (producción) compone los adaptadores
            reales. Los tests lo inyectan para no crear clientes AWS.

    Returns:
        Dict con `batchItemFailures`: ids de los mensajes que deben reintentarse
        (`{"batchItemFailures": [{"itemIdentifier": "..."}]}`); vacío si todo salió bien.

    Raises:
        pydantic.ValidationError: Si la configuración del consumer falta (fail fast).
    """
    settings = load_settings()
    configure_logging(settings.log_level)
    consumer_final = consumer if consumer is not None else _construir_consumer(settings)
    return {"batchItemFailures": consumer_final.process_batch(event)}


def _construir_consumer(settings: Settings) -> MessageConsumer:
    """Compone el consumer con los adaptadores reales (Bedrock, DynamoDB, Meta).

    Valida todos los ajustes antes de crear un solo cliente AWS (fail fast).

    Args:
        settings: Ajustes ya cargados del entorno.

    Returns:
        El consumer listo para procesar lotes SQS.

    Raises:
        ValidationError: Si faltan modelo o la tabla de conversaciones.
    """
    faltantes = [
        nombre
        for nombre, valor in (
            ("bedrock_model_id", settings.bedrock_model_id),
            ("conversations_table", settings.conversations_table),
        )
        if not valor
    ]
    if faltantes:
        raise ValidationError(
            "consumer incompleto: faltan ajustes del paso 9",
            details={"faltantes": ",".join(faltantes)},
        )
    llm = BedrockLLM(
        model_id=settings.bedrock_model_id, timeout_seconds=settings.bedrock_timeout_seconds
    )
    conversations = DynamoConversationStore(
        table_name=settings.conversations_table, ventana=settings.history_window_size
    )
    credentials = SsmCredentialStore()
    channel = MetaChannel(
        api_version=settings.meta_api_version,
        http_timeout_seconds=settings.meta_http_timeout_seconds,
        credentials=credentials,
        client=RequestsGraphClient(),
    )
    # Con `allowed_bots` vacío el supervisor no enruta a ningún especialista (todas las
    # intenciones de negocio se convierten en «servicio no disponible») y solo responde
    # él: saludo y degradaciones. Es el alcance mínimo del Commit B; los especialistas
    # y los entitlements por tenant se inyectan en el Commit C. El contexto de cliente
    # hoy es vacío (requisito 7.2: el turno no puede ir sin contexto); el adapter
    # DynamoDB del contexto llega también en el Commit C.
    grafo = build_supervisor_graph(
        llm=llm,
        context_reader=_LectorContextoVacio(),
        allowed_bots=frozenset(),
        appointments_graph=None,  # type: ignore[arg-type]  # TODO(decision): Commit C.
    )
    return MessageConsumer(
        grafo=grafo,
        conversations=conversations,
        channel=channel,
        ventana=settings.history_window_size,
    )
