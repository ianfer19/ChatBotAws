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


class CredentialNotFoundError(AppError):
    """El comercio no tiene credenciales (access token) en SSM para ese canal.

    El envío de respuestas (Fase 6) no puede hablar con Meta sin token: el error es
    interno del adaptador y nunca se muestra al usuario final (el consumer lo traduce
    a un reintento/alarma, no a un mensaje del bot).
    """

    code = "credential_not_found"
    http_status = 502


class AdminUnauthorizedError(AppError):
    """El endpoint admin no recibió el token propio mínimo (decisión 6, dev).

    El detalle del motivo jamás sale del handler: solo el código estable, para que
    un atacante no distinga «sin header» de «token malo».
    """

    code = "unauthorized"
    http_status = 401


class AdminMethodNotAllowedError(AppError):
    """El endpoint admin solo acepta `POST /admin/channels`."""

    code = "method_not_allowed"
    http_status = 405
