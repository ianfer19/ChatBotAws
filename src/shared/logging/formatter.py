"""Formatter JSON por línea para CloudWatch, con `tenant_id` y `correlation_id`.

Regla (MULTI_TENANCY §3): cada evento lleva ambos campos; se toman del `TenantContext`
activo, de modo que el llamador no puede olvidarlos. Un log emitido antes de fijar el
contexto (arranque frío) los trae en `null`.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from shared.context.tenant import current_context

_REDACTED = "***"
_REDACTED_KEYS = frozenset(
    {"token", "access_token", "app_secret", "secret", "password", "authorization"}
)

# Atributos propios de todo LogRecord: lo que quede en record.__dict__ es "extra".
_BASE_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__
) | {"message", "asctime", "exc_text"}


class JsonFormatter(logging.Formatter):
    """Convierte cada `LogRecord` en una línea JSON apta para CloudWatch Logs.

    Los valores de `extra` cuya clave coincida con un nombre sensible (token, secretos)
    se sustituyen por `***`; el resto se incluye tal cual (sin PII: es responsabilidad
    de quien loguea no meter PII en `message` ni en `extra`).
    """

    def format(self, record: logging.LogRecord) -> str:
        """Serializa el registro a JSON en una sola línea.

        Args:
            record: Registro de logging ya creado por el logger.

        Returns:
            Cadena JSON con timestamp, nivel, logger, mensaje, `tenant_id`,
            `correlation_id`, los campos `extra` y la excepción si la hay.
        """
        context = current_context()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "tenant_id": context.tenant_id if context else None,
            "correlation_id": context.correlation_id if context else None,
        }
        for key, value in record.__dict__.items():
            if key in _BASE_RECORD_ATTRS or key.startswith("_"):
                continue
            payload[key] = _REDACTED if key.lower() in _REDACTED_KEYS else value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)
