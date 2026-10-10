"""Caso de uso del webhook Meta: verificación de suscripción y aceptación de eventos.

La verificación (`hub.challenge`) y la firma (`X-Hub-Signature-256`) son comunes a
los 3 canales (ADR 0009): lo que difiere entre canales vive en los adaptadores
(`ChannelPort.normalize_inbound`, Fase 3). Este módulo no conoce API Gateway ni
Lambda; el handler traduce estos resultados a respuestas HTTP.
"""

import hmac
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from shared.errors import ValidationError
from shared.logging import get_logger
from slices.conversation_gateway.domain.channels import detect_channel
from slices.conversation_gateway.domain.errors import InvalidSignatureError
from slices.conversation_gateway.domain.signature import is_valid_signature

logger = get_logger(__name__)


class WebhookResponse(BaseModel):
    """Respuesta del caso de uso, ya traducible a HTTP por el handler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: int
    body: str


class WebhookReceiver:
    """Verificación (GET) y firma (POST) del webhook único de los canales Meta.

    A diferencia del legacy (que dejó la firma comentada en `app.py:65-68`), aquí la
    verificación es **obligatoria en todo entorno** (ADR 0006): sin firma válida no
    se procesa ni se encola nada.

    Example:
        >>> receptor = WebhookReceiver(verify_token="tok", app_secret="secreto")
        >>> respuesta = receptor.verify_subscription(
        ...     mode="subscribe", token="tok", challenge="12345"
        ... )
        >>> (respuesta.status, respuesta.body)
        (200, '12345')
    """

    def __init__(self, *, verify_token: str, app_secret: str) -> None:
        """Guarda los secretos de verificación (vienen del entorno, nunca del repo).

        Args:
            verify_token: Token acordado con Meta (`hub.verify_token`).
            app_secret: Secreto de la app Meta para verificar `X-Hub-Signature-256`.

        Raises:
            ValidationError: Si alguno falta o está vacío: la Lambda no debe
                arrancar «a medias» (fail fast en la composición).
        """
        if not verify_token or not app_secret:
            raise ValidationError("webhook incompleto: faltan verify_token o app_secret")
        self._verify_token = verify_token
        self._app_secret = app_secret

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
        """Verifica la firma, identifica el canal y acepta el evento del webhook.

        Args:
            raw_body: Cuerpo crudo del POST (los bytes exactos que firmó Meta).
            signature: Cabecera `X-Hub-Signature-256` (`None` si no venía).

        Returns:
            `200 EVENT_RECEIVED` si el envelope es de un canal Meta (el procesamiento
            —normalizar, resolver tenant, deduplicar y encolar— llega en la Fase 4);
            `200 EVENT_IGNORED` si no corresponde a ninguno de los 3 canales.

        Raises:
            InvalidSignatureError: Si la firma falta o no coincide (handler → 403).
            ValidationError: Si el cuerpo firmado no es un objeto JSON.
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
        # Fase 4: aquí se inserta el flujo normalize → resolve tenant → dedup →
        # encolado (ADR 0009: el adaptador interpreta el mensaje ANTES de encolarlo).
        logger.info("webhook.event_accepted", extra={"channel": channel})
        return WebhookResponse(status=200, body="EVENT_RECEIVED")

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
