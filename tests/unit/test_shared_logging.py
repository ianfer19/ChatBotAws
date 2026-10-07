"""Tests del kernel: logger JSON con tenant/correlación y redacción (shared/logging)."""

import json
import logging
import sys
from datetime import datetime
from typing import Any

from shared.context import TenantContext, bind_context, current_context
from shared.logging import JsonFormatter, configure_logging, get_logger


def _record(message: str = "evento", exc_info: Any = None, **extra: Any) -> logging.LogRecord:
    """LogRecord sintético con los campos `extra` dados."""
    record = logging.LogRecord(
        name="tests.kernel",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _format(record: logging.LogRecord) -> dict[str, Any]:
    """Formatea el registro y devuelve el JSON resultante."""
    raw = JsonFormatter().format(record)
    assert "\n" not in raw, "el formato debe ser una línea por evento"
    payload: dict[str, Any] = json.loads(raw)
    return payload


def _context() -> TenantContext:
    """Contexto sintético de prueba."""
    return TenantContext(
        tenant_id="Sede_Elite_01",
        correlation_id="corr-log-001",
        channel="whatsapp",
        customer_id="57300111111",
    )


def test_incluye_tenant_y_correlation_del_contexto() -> None:
    """Regla MULTI_TENANCY §3: todo log lleva `tenant_id` y `correlation_id`."""
    assert current_context() is None
    with bind_context(_context()):
        payload = _format(_record("turno procesado"))
    assert payload["tenant_id"] == "Sede_Elite_01"
    assert payload["correlation_id"] == "corr-log-001"
    assert payload["message"] == "turno procesado"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "tests.kernel"
    assert payload["timestamp"].startswith("20")  # ISO 8601 con zona horaria


def test_antes_de_resolver_el_tenant_los_campos_vienen_nulos() -> None:
    """El logger funciona en el arranque frío, previo a fijar el contexto."""
    assert current_context() is None
    payload = _format(_record("arranque"))
    assert payload["tenant_id"] is None
    assert payload["correlation_id"] is None


def test_redacta_secretos_puestos_en_extra() -> None:
    """Nunca se loguean tokens ni secretos: la clave sensible se sustituye por `***`."""
    payload = _format(_record("envío", access_token="EAAB...", password="hunter2"))
    assert payload["access_token"] == "***"
    assert payload["password"] == "***"
    assert "EAAB..." not in json.dumps(payload)
    assert "hunter2" not in json.dumps(payload)


def test_incluye_la_excepcion_si_la_hay() -> None:
    """Los errores se registran con su traza dentro del JSON (para CloudWatch)."""
    try:
        msg = "fallo deliberado"
        raise ValueError(msg)
    except ValueError:
        payload = _format(_record("error al procesar", exc_info=sys.exc_info()))
    assert "exception" in payload
    assert "ValueError: fallo deliberado" in payload["exception"]


def test_configure_logging_es_idempotente() -> None:
    """Llamar dos veces no duplica el handler JSON en el logger raíz."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        root.handlers = []
        configure_logging("DEBUG")
        configure_logging("DEBUG")
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(json_handlers) == 1
        assert root.level == logging.DEBUG
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_get_logger_devuelve_logger_con_el_nombre_dado() -> None:
    """`get_logger` es un alias de `logging.getLogger` con el nombre del módulo."""
    logger = get_logger("slices.supervisor")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "slices.supervisor"


def test_timestamp_es_consciente_de_zona_horaria() -> None:
    """El timestamp del log es aware (UTC), nunca hora local ingenua."""
    payload = _format(_record())
    assert datetime.fromisoformat(payload["timestamp"]).tzinfo is not None
