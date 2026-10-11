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
    monkeypatch.setenv("CHATBOT_BEDROCK_MODEL_ID", "anthropic.claude-haiku")
    monkeypatch.setenv("CHATBOT_BEDROCK_TIMEOUT_SECONDS", "7")
    settings = load_settings()
    assert settings.environment == "staging"
    assert settings.log_level == "WARNING"
    assert settings.bedrock_model_id == "anthropic.claude-haiku"
    assert settings.bedrock_timeout_seconds == 7


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


def test_modelo_de_bedrock_es_obligatorio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin modelo no arrancamos: `CHATBOT_BEDROCK_MODEL_ID` vacío debe fallar (fail fast)."""
    monkeypatch.delenv("CHATBOT_BEDROCK_MODEL_ID", raising=False)
    with pytest.raises(PydanticValidationError):
        Settings()


def test_timeout_de_bedrock_por_defecto_y_personalizado(monkeypatch: pytest.MonkeyPatch) -> None:
    """El timeout por defecto es 30 s y se puede ajustar; valores < 1 se rechazan."""
    monkeypatch.delenv("CHATBOT_BEDROCK_TIMEOUT_SECONDS", raising=False)
    assert load_settings().bedrock_timeout_seconds == 30

    monkeypatch.setenv("CHATBOT_BEDROCK_TIMEOUT_SECONDS", "5")
    assert load_settings().bedrock_timeout_seconds == 5

    monkeypatch.setenv("CHATBOT_BEDROCK_TIMEOUT_SECONDS", "0")
    with pytest.raises(PydanticValidationError):
        Settings()


def test_ventana_de_historial_por_defecto_y_personalizada(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ventana de historial (Paso 8) arranca en 10 y no admite menos de 1."""
    monkeypatch.delenv("CHATBOT_HISTORY_WINDOW_SIZE", raising=False)
    assert load_settings().history_window_size == 10

    monkeypatch.setenv("CHATBOT_HISTORY_WINDOW_SIZE", "6")
    assert load_settings().history_window_size == 6

    monkeypatch.setenv("CHATBOT_HISTORY_WINDOW_SIZE", "0")
    with pytest.raises(PydanticValidationError):
        Settings()


def test_tabla_de_checkpoints_por_defecto_y_personalizada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La tabla del checkpointer (Paso 8) es opcional a nivel de Settings y no negativa."""
    monkeypatch.delenv("CHATBOT_CHECKPOINTS_TABLE", raising=False)
    assert load_settings().checkpoints_table == ""

    monkeypatch.setenv("CHATBOT_CHECKPOINTS_TABLE", "chatbot_checkpoints_dev")
    assert load_settings().checkpoints_table == "chatbot_checkpoints_dev"


def test_secretos_del_webhook_opcionales_y_desde_entorno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los secretos del webhook (Paso 9) no obligan al resto de procesos a definirlos."""
    monkeypatch.delenv("CHATBOT_WEBHOOK_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("CHATBOT_META_APP_SECRET", raising=False)
    assert load_settings().webhook_verify_token == ""
    assert load_settings().meta_app_secret == ""

    monkeypatch.setenv("CHATBOT_WEBHOOK_VERIFY_TOKEN", "token-meta")
    monkeypatch.setenv("CHATBOT_META_APP_SECRET", "secreto-app")
    settings = load_settings()
    assert settings.webhook_verify_token == "token-meta"
    assert settings.meta_app_secret == "secreto-app"


def test_tablas_del_consumer_opcionales_y_desde_entorno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las tablas del consumer (Paso 9, Fase 6) no obligan al resto de procesos a definirlas."""
    monkeypatch.delenv("CHATBOT_CONVERSATIONS_TABLE", raising=False)
    monkeypatch.delenv("CHATBOT_CUSTOMER_CONTEXT_TABLE", raising=False)
    assert load_settings().conversations_table == ""
    assert load_settings().customer_context_table == ""

    monkeypatch.setenv("CHATBOT_CONVERSATIONS_TABLE", "chatbot_conversations_dev")
    monkeypatch.setenv("CHATBOT_CUSTOMER_CONTEXT_TABLE", "chatbot_customer_context_dev")
    settings = load_settings()
    assert settings.conversations_table == "chatbot_conversations_dev"
    assert settings.customer_context_table == "chatbot_customer_context_dev"
