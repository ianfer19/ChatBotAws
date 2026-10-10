"""Errores tipados del gateway de conversación: los handlers los traducen a respuesta.

Subclases de `shared.errors.AppError` con `code` estable para logs, métricas y tests;
el mensaje es para el log, nunca se muestra tal cual al usuario final.
"""

from shared.errors import AppError


class InvalidSignatureError(AppError):
    """La cabecera `X-Hub-Signature-256` no coincide con el cuerpo (o falta).

    Regla 1 del slice: sin firma válida no se procesa nada; el usuario solo ve 403
    sin detalle y el log de auditoría conserva el por qué.
    """

    code = "invalid_signature"
    http_status = 403


class DuplicateMessageError(AppError):
    """Meta reenvió un `message_id` ya procesado: se acusa con 200 y no se reprocesa.

    `http_status = 200` a propósito: no es un error para el emisor (si respondiéramos
    4xx/5xx, Meta reintentaría indefinidamente). El handler lo traduce a un acuse
    silencioso sin invocar al supervisor.
    """

    code = "duplicate_message"
    http_status = 200
