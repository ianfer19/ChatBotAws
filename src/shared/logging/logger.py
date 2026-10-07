"""Instalación del logger JSON y fábrica de loggers."""

import logging

from shared.logging.formatter import JsonFormatter


def configure_logging(level: str = "INFO") -> None:
    """Instala el handler JSON en el logger raíz; idempotente.

    Si la raíz ya tiene un handler con `JsonFormatter` (arranque repetido o test),
    no duplica. Los demás handlers existentes se conservan.

    Args:
        level: Nivel del logger raíz (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

    Raises:
        ValueError: Si el nivel no es reconocido por `logging`.
    """
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Logger con el nombre del módulo que llama (salida ya estructurada vía la raíz).

    Args:
        name: Nombre del logger, normalmente `__name__`.

    Returns:
        El logger registrado en `logging` con ese nombre.
    """
    return logging.getLogger(name)
