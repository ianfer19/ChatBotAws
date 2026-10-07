"""Configuración global leída de variables de entorno con Pydantic Settings."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes del sistema desde el entorno, con prefijo `CHATBOT_`.

    Campos hoy (Fase 2): entorno de despliegue y nivel de log. Cada fase añade los
    suyos (Bedrock, colas, etc.) en vez de estandarizar configuración que aún no existe.

    Example:
        Con `CHATBOT_ENVIRONMENT=staging` en el entorno:
        >>> Settings().environment
        'staging'
    """

    model_config = SettingsConfigDict(env_prefix="CHATBOT_", extra="ignore")

    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


def load_settings() -> Settings:
    """Carga `Settings` desde las variables de entorno del proceso.

    Returns:
        Instancia validada; sin caché para que cada handler pueda recargarla en tests.

    Raises:
        pydantic.ValidationError: Si alguna variable de entorno no es válida.
    """
    return Settings()
