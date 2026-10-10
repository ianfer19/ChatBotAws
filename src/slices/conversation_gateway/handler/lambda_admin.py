"""Composition root del endpoint admin: `POST /admin/channels` → alta de canal.

Mismo criterio que `lambda_webhook.py`: único punto que conoce el evento de API
Gateway y la composición real (DynamoDB + SSM); el caso de uso solo ve puertos.
La autenticación es un token propio mínimo comparado en tiempo constante
(decisión 6 del Paso 9: sin authorizer completo en dev).
"""

import base64
import hmac
import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError as ValidationErrorPydantic

from shared.config import Settings, load_settings
from shared.errors import AppError, ValidationError
from shared.logging import configure_logging, get_logger
from slices.conversation_gateway.application.admin import AdminChannelRequest, AdminChannelsUseCase
from slices.conversation_gateway.domain.errors import (
    AdminMethodNotAllowedError,
    AdminUnauthorizedError,
)
from slices.conversation_gateway.infrastructure.dynamodb import DynamoChannelMapping
from slices.conversation_gateway.infrastructure.ssm import SsmCredentialStore

logger = get_logger(__name__)

_CABECERA_TOKEN = "x-admin-token"


def main(
    event: dict[str, Any],
    _context: Any,
    caso: AdminChannelsUseCase | None = None,
) -> dict[str, Any]:
    """Entrada Lambda del endpoint admin (solo `POST /admin/channels`).

    Args:
        event: Payload 2.0 de API Gateway HTTP API (`requestContext.http.method`,
            `headers`, `rawBody`).
        _context: Contexto de Lambda (no usado: la composición es síncrona).
        caso: Caso de uso ya compuesto; `None` (producción) compone los
            adaptadores reales. Los tests lo inyectan para no crear clientes AWS.

    Returns:
        Respuesta de API Gateway: `201 {"ok": true}` en éxito; en error,
        el código estable del `AppError` (`400` validación, `401` token,
        `5xx` servicios) sin trazas ni secretos.

    Raises:
        pydantic.ValidationError: Si la configuración admin falta (fail fast).
    """
    settings = load_settings()
    configure_logging(settings.log_level)
    caso_final = caso if caso is not None else _construir_caso(settings)
    try:
        _exigir_post(event)
        _exigir_token(event, settings.admin_token)
        request = _validar_cuerpo(_cuerpo(event))
        caso_final.register_channel(request)
        logger.info("admin.ok", extra={"channel": request.channel})
    except AppError as exc:
        logger.warning("admin.rejected", extra={"error": exc.code})
        return _respuesta(exc.http_status, {"error": exc.code})
    return _respuesta(201, {"ok": True})


def _construir_caso(settings: Settings) -> AdminChannelsUseCase:
    """Compone el caso de uso con los adaptadores reales (DynamoDB + SSM).

    Valida los ajustes antes de crear un solo cliente AWS (fail fast).

    Args:
        settings: Ajustes ya cargados del entorno.

    Returns:
        El caso de uso listo para registrar canales.

    Raises:
        ValidationError: Si faltan `admin_token` o `channel_mapping_table`.
    """
    faltantes = [
        nombre
        for nombre, valor in (
            ("admin_token", settings.admin_token),
            ("channel_mapping_table", settings.channel_mapping_table),
        )
        if not valor
    ]
    if faltantes:
        raise ValidationError(
            "admin incompleto: faltan ajustes del paso 9",
            details={"faltantes": ",".join(faltantes)},
        )
    return AdminChannelsUseCase(
        mapping=DynamoChannelMapping(table_name=settings.channel_mapping_table),
        credentials=SsmCredentialStore(),
    )


def _exigir_post(event: Mapping[str, Any]) -> None:
    """Rechaza cualquier método distinto de `POST` (405).

    Args:
        event: Payload 2.0 de API Gateway.

    Raises:
        AdminMethodNotAllowedError: Si el método no es `POST` (405).
    """
    request_context: Any = event.get("requestContext") or {}
    http: Any = request_context.get("http") or {}
    if str(http.get("method") or "") != "POST":
        raise AdminMethodNotAllowedError("metodo no soportado en el admin")


def _exigir_token(event: Mapping[str, Any], token_esperado: str) -> None:
    """Compara el token del header con el configurado (tiempo constante).

    Args:
        event: Payload 2.0 de API Gateway.
        token_esperado: `CHATBOT_ADMIN_TOKEN` (ya validado por la composición).

    Raises:
        AdminUnauthorizedError: Si el token no coincide o falta (401, sin detalle).
    """
    if not token_esperado:
        raise ValidationError("CHATBOT_ADMIN_TOKEN vacio en el admin")
    headers = {clave.lower(): valor for clave, valor in (event.get("headers") or {}).items()}
    recibido = headers.get(_CABECERA_TOKEN) or ""
    if not hmac.compare_digest(recibido.encode("utf-8"), token_esperado.encode("utf-8")):
        raise AdminUnauthorizedError("token de admin invalido")


def _cuerpo(event: Mapping[str, Any]) -> str:
    """Extrae el cuerpo como texto (con base64 si API Gateway lo marcó).

    Args:
        event: Payload 2.0 de API Gateway.

    Returns:
        El cuerpo como texto plano para validarlo con Pydantic.
    """
    cuerpo: str = event.get("rawBody") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(cuerpo).decode("utf-8")
    return cuerpo


def _validar_cuerpo(cuerpo: str) -> AdminChannelRequest:
    """Valida el JSON del cuerpo contra el modelo del caso de uso.

    Args:
        cuerpo: Texto crudo del `rawBody`.

    Returns:
        El request validado y con tipado estricto.

    Raises:
        ValidationError: Si el JSON es inválido, sobran campos o falta alguno.
    """
    try:
        return AdminChannelRequest.model_validate_json(cuerpo)
    except ValidationErrorPydantic as exc:
        raise ValidationError(
            "cuerpo invalido en el alta de canal",
            details={"errores": str(len(exc.errors()))},
        ) from exc


def _respuesta(status: int, cuerpo: dict[str, Any]) -> dict[str, Any]:
    """Convierte estado + cuerpo al formato de API Gateway.

    Args:
        status: Código HTTP.
        cuerpo: Diccionario JSON de la respuesta.

    Returns:
        Dict `statusCode`/`headers`/`body` con `application/json`.
    """
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(cuerpo),
    }
