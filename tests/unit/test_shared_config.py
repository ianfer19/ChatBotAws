"""Tests del kernel: configuración desde variables de entorno (shared/config)."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from shared.config import Settings, load_settings


def test_valores_por_defecto_sin_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin `CHATBOT_*` en el entorno, el sistema arranca en dev con log INFO."""
    monkeypatch.delenv("CHATBOT_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CHATBOT_LOG_LEVEL", raising=False)
    settings = load_settings()
    assert settings.environment == "dev"
    assert settings.log_level == "INFO"


def test_lee_las_variables_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """`load_settings` refleja lo que haya en las variables de entorno del proceso."""
    monkeypatch.setenv("CHATBOT_ENVIRONMENT", "staging")
    monkeypatch.setenv("CHATBOT_LOG_LEVEL", "WARNING")
    settings = load_settings()
    assert settings.environment == "staging"
    assert settings.log_level == "WARNING"


def test_entorno_invalido_falla_en_arranque(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un valor inválido detiene el arranque (fail fast) en vez de degradar en silencio."""
    monkeypatch.setenv("CHATBOT_ENVIRONMENT", "produccion")
    with pytest.raises(PydanticValidationError):
        Settings()


def test_ignora_variables_ajenas_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """El entorno de una Lambda tiene muchas variables ajenas: no deben romper config."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("CHATBOT_ENVIRONMENT", "dev")
    assert load_settings().environment == "dev"
