"""Composition root del webhook Meta: evento de API Gateway → caso de uso → respuesta.

Único punto que conoce el formato del evento (payload 2.0 de API Gateway HTTP API);
el caso de uso solo ve argumentos planos y los errores tipados se traducen aquí a
respuestas HTTP sin filtrar trazas (shared/AGENTS: los handlers traducen, jamás el
stack trace al usuario final).
"""

import base64
import json
from collections.abc import Mapping
from typing import Any

from shared.config import load_settings
from shared.errors import AppError
from shared.logging import configure_logging, get_logger
from slices.conversation_gateway.application.webhook import WebhookReceiver, WebhookResponse

logger = get_logger(__name__)

_FIRMA = "x-hub-signature-256"


def main(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Entrada Lambda de la webhook Meta (GET verificación / POST eventos).

    Args:
        event: Payload 2.0 de API Gateway HTTP API (`requestContext.http.method`,
            `headers`, `queryStringParameters`, `rawBody`).
        _context: Contexto de Lambda (no usado: la composición es síncrona).

    Returns:
        Respuesta de API Gateway: `statusCode`, `headers` y `body`.

    Raises:
        pydantic.ValidationError: Si la configuración del webhook falta o es
            inválida (fail fast: la Lambda no debe responder a medias).
    """
    settings = load_settings()
    configure_logging(settings.log_level)
    receiver = WebhookReceiver(
        verify_token=settings.webhook_verify_token,
        app_secret=settings.meta_app_secret,
    )
    try:
        respuesta = _despachar(event, receiver)
    except AppError as exc:
        # Solo el código estable, nunca `details` ni traza (403 «sin detalle»).
        logger.warning("webhook.rejected", extra={"error": exc.code})
        respuesta = WebhookResponse(status=exc.http_status, body=json.dumps({"error": exc.code}))
    return _respuesta_http(respuesta)


def _despachar(event: Mapping[str, Any], receiver: WebhookReceiver) -> WebhookResponse:
    """Traduce el evento al método adecuado del caso de uso.

    Args:
        event: Payload 2.0 de API Gateway.
        receiver: Caso de uso del webhook ya construido con los secretos.

    Returns:
        La respuesta del caso de uso.

    Raises:
        AppError: Cualquier error tipado del dominio/aplicación (lo traduce `main`).
    """
    metodo = _metodo(event)
    if metodo == "GET":
        params = event.get("queryStringParameters") or {}
        return receiver.verify_subscription(
            mode=params.get("hub.mode"),
            token=params.get("hub.verify_token"),
            challenge=params.get("hub.challenge"),
        )
    if metodo == "POST":
        headers = {clave.lower(): valor for clave, valor in (event.get("headers") or {}).items()}
        return receiver.receive(
            raw_body=_cuerpo(event),
            signature=headers.get(_FIRMA),
        )
    logger.warning("webhook.unsupported_method", extra={"method": metodo})
    return WebhookResponse(status=405, body="method_not_allowed")


def _metodo(event: Mapping[str, Any]) -> str:
    """Extrae el método HTTP del evento (payload 2.0).

    Args:
        event: Payload 2.0 de API Gateway.

    Returns:
        El método en mayúsculas o `""` si la ruta no lo trae.
    """
    request_context: Any = event.get("requestContext") or {}
    http: Any = request_context.get("http") or {}
    metodo: Any = http.get("method") or ""
    return str(metodo)


def _cuerpo(event: Mapping[str, Any]) -> bytes:
    """Extrae el cuerpo crudo como bytes exactos (los que firmó Meta).

    Args:
        event: Payload 2.0 de API Gateway.

    Returns:
        El cuerpo en bytes, decodificando de base64 si API Gateway lo marcó.
    """
    cuerpo: str = event.get("rawBody") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(cuerpo)
    return cuerpo.encode("utf-8")


def _respuesta_http(respuesta: WebhookResponse) -> dict[str, Any]:
    """Convierte la respuesta del caso de uso al formato de API Gateway.

    Args:
        respuesta: Estado y cuerpo ya decididos por el caso de uso o `main`.

    Returns:
        Dict `statusCode`/`headers`/`body`; `text/plain` para el challenge de Meta
        (lo devuelve tal cual) y `application/json` para los errores.
    """
    content_type = "text/plain; charset=utf-8" if respuesta.status < 400 else "application/json"
    return {
        "statusCode": respuesta.status,
        "headers": {"content-type": content_type},
        "body": respuesta.body,
    }
