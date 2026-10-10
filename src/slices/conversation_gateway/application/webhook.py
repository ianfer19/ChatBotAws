"""Caso de uso del webhook Meta: verificación, firma, deduplicación y encolado.

La verificación (`hub.challenge`) y la firma (`X-Hub-Signature-256`) son comunes a
los 3 canales (ADR 0009): lo que difiere entre canales vive en los adaptadores
(`NormalizerPort.normalize_inbound`, Fase 3). El flujo de un evento es:

    firma → detectar canal → normalizar → resolver tenant → deduplicar → encolar

y termina en `SQS` (Fase 4): el consumer (Fase 6) persiste y llama al supervisor.
Este módulo no conoce API Gateway ni Lambda; el handler traduce estos resultados a
respuestas HTTP. La cola desacopla recepción de procesamiento: el webhook solo
acusa a Meta en menos de 5 s y jamás invoca al agente en línea.
"""

import hmac
import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from shared.contracts import QueuedMessage
from shared.contracts.types import Channel
from shared.errors import AppError, TenantNotFoundError, ValidationError
from shared.logging import get_logger
from shared.ports import ChannelMessage, EventBusPort
from slices.conversation_gateway.domain.channels import detect_channel
from slices.conversation_gateway.domain.errors import (
    DuplicateMessageError,
    InvalidSignatureError,
)
from slices.conversation_gateway.domain.ports import (
    DeduplicationPort,
    NormalizerPort,
    TenantResolverPort,
)
from slices.conversation_gateway.domain.signature import is_valid_signature

logger = get_logger(__name__)

_EVENTO_INBOUND = "inbound.message"
# Nombre estable del evento en la cola (EventBusPort); el consumer lo despacha.


class WebhookResponse(BaseModel):
    """Respuesta del caso de uso, ya traducible a HTTP por el handler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: int
    body: str


class WebhookReceiver:
    """Verificación (GET), firma (POST) y encolado del webhook único de los canales Meta.

    A diferencia del legacy (que dejó la firma comentada en `app.py:65-68`), aquí la
    verificación es **obligatoria en todo entorno** (ADR 0006): sin firma válida no
    se procesa ni se encola nada. Los cuatro puertos (normalizador, tenant, dedup y
    bus) se inyectan: en producción son DynamoDB + SQS y en tests dobles en memoria.

    Example:
        >>> from slices.conversation_gateway.infrastructure.in_memory import (
        ...     InMemoryChannel,
        ...     InMemoryDeduplication,
        ...     InMemoryEventBus,
        ...     InMemoryTenantResolver,
        ... )
        >>> receptor = WebhookReceiver(
        ...     verify_token="tok",
        ...     app_secret="secreto",
        ...     normalizer=InMemoryChannel(),
        ...     tenants=InMemoryTenantResolver(),
        ...     dedup=InMemoryDeduplication(),
        ...     bus=InMemoryEventBus(),
        ... )
        >>> respuesta = receptor.verify_subscription(
        ...     mode="subscribe", token="tok", challenge="12345"
        ... )
        >>> (respuesta.status, respuesta.body)
        (200, '12345')
    """

    def __init__(
        self,
        *,
        verify_token: str,
        app_secret: str,
        normalizer: NormalizerPort,
        tenants: TenantResolverPort,
        dedup: DeduplicationPort,
        bus: EventBusPort,
    ) -> None:
        """Guarda los secretos y los puertos del flujo de entrada.

        Args:
            verify_token: Token acordado con Meta (`hub.verify_token`).
            app_secret: Secreto de la app Meta para verificar `X-Hub-Signature-256`.
            normalizer: Adaptador que traduce el payload de su canal a `ChannelMessage`.
            tenants: Resolución `emitter_id → tenant_id` (mapeo del legacy).
            dedup: Idempotencia por `tenant_id` + `message_id`.
            bus: Transporte hacia el consumer (SQS en producción).

        Raises:
            ValidationError: Si faltan los secretos: la Lambda no debe arrancar
                «a medias» (fail fast en la composición).
        """
        if not verify_token or not app_secret:
            raise ValidationError("webhook incompleto: faltan verify_token o app_secret")
        self._verify_token = verify_token
        self._app_secret = app_secret
        self._normalizer = normalizer
        self._tenants = tenants
        self._dedup = dedup
        self._bus = bus

    def verify_subscription(
        self, *, mode: str | None, token: str | None, challenge: str | None
    ) -> WebhookResponse:
        """Responde a la verificación GET de Meta (`hub.mode`, `hub.verify_token`, `hub.challenge`).

        Args:
            mode: Valor de `hub.mode`; Meta envía `subscribe`.
            token: Valor de `hub.verify_token`; se compara en tiempo constante.
            challenge: Valor de `hub.challenge` que hay que devolver tal cual.

        Returns:
            `200` con el challenge si todo coincide; `403` en cualquier otro caso
            (sin revelar cuál de los tres falló).

        Raises:
            (nunca): cualquier entrada inválida se traduce en `403`.
        """
        coincide = token is not None and hmac.compare_digest(
            token.encode("utf-8"), self._verify_token.encode("utf-8")
        )
        if mode == "subscribe" and challenge and coincide:
            return WebhookResponse(status=200, body=challenge)
        # Nunca loguear el token: solo el motivo estructurado.
        logger.warning("webhook.challenge_rejected", extra={"mode": mode})
        return WebhookResponse(status=403, body=json.dumps({"error": "forbidden"}))

    def receive(self, *, raw_body: bytes, signature: str | None) -> WebhookResponse:
        """Verifica la firma, normaliza el evento, deduplica y encola cada mensaje.

        Args:
            raw_body: Cuerpo crudo del POST (los bytes exactos que firmó Meta).
            signature: Cabecera `X-Hub-Signature-256` (`None` si no venía).

        Returns:
            `200 EVENT_RECEIVED` si el envelope es de un canal Meta (con mensajes
            encolados o sin mensajes procesables); `200 EVENT_IGNORED` si no
            corresponde a ninguno de los 3 canales; `200 EVENT_TENANT_UNKNOWN` si
            algún emisor no tiene mapeo (se acusa a Meta para que no reintente; sin
            mapeo no hay credenciales con qué responderle al usuario — ver el
            `AGENTS.md` del slice). Si **todos** los mensajes ya estaban encolados,
            levanta `DuplicateMessageError` (handler → 200 `EVENT_DUPLICATED`).

        Raises:
            InvalidSignatureError: Si la firma falta o no coincide (handler → 403).
            ValidationError: Si el cuerpo firmado no es un objeto JSON.
            DuplicateMessageError: Si todos los mensajes del evento ya se procesaron.
            ToolError: Si la cola falla (handler → 502 y Meta reintenta); antes de
                re-lanzar se libera la deduplicación para no perder el mensaje.
        """
        if not is_valid_signature(
            payload=raw_body, signature=signature, app_secret=self._app_secret
        ):
            logger.warning(
                "webhook.invalid_signature",
                extra={"signature_present": signature is not None, "body_bytes": len(raw_body)},
            )
            raise InvalidSignatureError("firma X-Hub-Signature-256 inválida")
        payload = self._parsear(raw_body)
        channel = detect_channel(payload)
        if channel is None:
            logger.info("webhook.event_ignored")
            return WebhookResponse(status=200, body="EVENT_IGNORED")
        mensajes = self._normalizer.normalize_inbound(payload, channel=channel)
        if not mensajes:
            logger.info("webhook.event_accepted", extra={"channel": channel, "encolados": 0})
            return WebhookResponse(status=200, body="EVENT_RECEIVED")
        tenant_por_emisor = self._resolver_tenantes(mensajes, channel=channel)
        if tenant_por_emisor is None:
            return WebhookResponse(status=200, body="EVENT_TENANT_UNKNOWN")
        encolados, duplicados = self._encolar(
            mensajes,
            tenant_por_emisor=tenant_por_emisor,
            raw_body=raw_body,
        )
        logger.info(
            "webhook.event_accepted",
            extra={
                "channel": channel,
                "tenant_id": next(iter(tenant_por_emisor.values())),
                "encolados": encolados,
                "duplicados": duplicados,
            },
        )
        if encolados == 0:
            raise DuplicateMessageError(
                "todos los mensajes del evento ya estaban encolados",
                details={"channel": channel, "duplicados": str(duplicados)},
            )
        return WebhookResponse(status=200, body="EVENT_RECEIVED")

    def _resolver_tenantes(
        self, mensajes: list[ChannelMessage], *, channel: Channel
    ) -> dict[str, str] | None:
        """Resuelve (con caché por emisor) el tenant de todos los mensajes del envelope.

        Se resuelve **antes** de encolar ninguno: un envelope con un emisor sin
        mapeo se acusa completo como `EVENT_TENANT_UNKNOWN` sin dejar mensajes a
        medias en la cola.

        Args:
            mensajes: Mensajes ya normalizados por el adaptador de canal.
            channel: Canal detectado en el envelope.

        Returns:
            Mapa `emitter_id → tenant_id`, o `None` si algún emisor no tiene
            mapeo (ya quedó logueado como `webhook.tenant_unknown`).

        Raises:
            ValidationError: Si un `emitter_id` llega vacío (payload malformado).
        """
        cache: dict[str, str] = {}
        for mensaje in mensajes:
            if mensaje.emitter_id in cache:
                continue
            try:
                cache[mensaje.emitter_id] = self._tenants.resolve(
                    channel=channel, emitter_id=mensaje.emitter_id
                )
            except TenantNotFoundError:
                logger.warning(
                    "webhook.tenant_unknown",
                    extra={"channel": channel, "emitter_id": mensaje.emitter_id},
                )
                return None
        return cache

    def _encolar(
        self,
        mensajes: list[ChannelMessage],
        *,
        tenant_por_emisor: dict[str, str],
        raw_body: bytes,
    ) -> tuple[int, int]:
        """Registra cada mensaje (deduplicación) y lo publica en la cola.

        Args:
            mensajes: Mensajes ya normalizados por el adaptador de canal.
            tenant_por_emisor: Mapa `emitter_id → tenant_id` ya resuelto.
            raw_body: Cuerpo crudo firmado que se persistirá como `raw_payload`.

        Returns:
            Tupla `(encolados, duplicados)` para el log estructurado del evento.

        Raises:
            ToolError: Si el bus falla; antes se libera la deduplicación de ese
                mensaje para que el reintento de Meta no lo pierda como duplicado.
        """
        raw_text = raw_body.decode("utf-8")  # ya validado: json.loads lo aceptó
        encolados = 0
        duplicados = 0
        for mensaje in mensajes:
            tenant_id = tenant_por_emisor[mensaje.emitter_id]
            if not self._dedup.register_once(tenant_id=tenant_id, message_id=mensaje.message_id):
                duplicados += 1
                continue
            evento = QueuedMessage(
                tenant_id=tenant_id,
                correlation_id=uuid.uuid4().hex,
                channel=mensaje.channel,
                emitter_id=mensaje.emitter_id,
                customer_id=mensaje.customer_id,
                message_id=mensaje.message_id,
                timestamp=mensaje.timestamp,
                text=mensaje.text,
                message_type=mensaje.message_type,
                sender_name=mensaje.sender_name,
                media_id=mensaje.media_id,
                media_type=mensaje.media_type,
                media_url=mensaje.media_url,
                raw_payload=raw_text,
            )
            try:
                self._bus.publish(_EVENTO_INBOUND, evento.model_dump(mode="json"))
            except Exception:
                # Rollback de la deduplicación: sin él, el reintento de Meta se
                # marcaría duplicado y el mensaje se perdería para siempre.
                self._liberar_dedup(tenant_id=tenant_id, message_id=mensaje.message_id)
                raise
            encolados += 1
        return (encolados, duplicados)

    def _liberar_dedup(self, *, tenant_id: str, message_id: str) -> None:
        """Libera la clave de deduplicación tras un encolado fallido (best-effort).

        Args:
            tenant_id: Comercio del mensaje.
            message_id: Id del mensaje en el canal.

        Returns:
            None; si la liberación también falla solo queda el log de error (el
            error original del bus es el que debe responder el handler).

        Raises:
            (nunca): las excepciones se tragan para no enmascarar el fallo del bus.
        """
        try:
            self._dedup.release(tenant_id=tenant_id, message_id=message_id)
        except AppError:
            logger.error(
                "webhook.dedup_release_failed",
                extra={"tenant_id": tenant_id, "message_id": message_id},
            )

    @staticmethod
    def _parsear(raw_body: bytes) -> dict[str, Any]:
        """Convierte el cuerpo firmado en un objeto JSON.

        Args:
            raw_body: Cuerpo crudo del POST (firma ya verificada).

        Returns:
            El payload como diccionario.

        Raises:
            ValidationError: Si no es JSON válido o no es un objeto (Meta envía
                siempre objetos; cualquier otra cosa es un ataque o un bug).
        """
        try:
            payload: Any = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("el cuerpo del webhook no es JSON válido") from exc
        if not isinstance(payload, dict):
            raise ValidationError("el cuerpo del webhook no es un objeto JSON")
        return payload
