"""Configuración global leída de variables de entorno con Pydantic Settings."""

from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes del sistema desde el entorno, con prefijo `CHATBOT_`.

    Campos: entorno de despliegue, nivel de log, modelo de Bedrock y timeout de su
    cliente (Paso 2), y desde el Paso 7 los de RAG: modelo de embeddings y
    conexión a Aurora. Los de RAG son opcionales a nivel de `Settings` (solo el
    proceso que compone el RAG los exige) y el constructor del adapter falla
    rápido si faltan. Cada paso añade los suyos en vez de estandarizar
    configuración que aún no existe.

    `bedrock_model_id` es **obligatorio**: sin modelo no hay conversación, así que el
    proceso falla al arrancar en lugar de fallar en el primer mensaje (fail fast).
    `TODO(verify)`: fijar versión mínima de `boto3` y precio del modelo (Paso 14).

    Example:
        Con `CHATBOT_BEDROCK_MODEL_ID` en el entorno:
        >>> settings = Settings(bedrock_model_id="modelo-de-prueba")
        >>> settings.environment, settings.bedrock_timeout_seconds
        ('dev', 30)
    """

    model_config = SettingsConfigDict(env_prefix="CHATBOT_", extra="ignore")

    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Default vacío solo para que la carga desde el entorno funcione: la validación
    # posterior rechaza el arranque si nadie lo define.
    bedrock_model_id: str = Field(default="")
    bedrock_timeout_seconds: int = Field(default=30, ge=1)
    # Paso 7 (RAG): el adapter de embeddings exige `bedrock_embeddings_model_id`
    # al construirse; `dimensions` debe coincidir con `vector(...)` de pgvector.
    bedrock_embeddings_model_id: str = Field(default="")
    bedrock_embeddings_dimensions: int = Field(default=1536, ge=1)
    # Paso 7 (Aurora): `aurora_host`/`aurora_dbname`/`aurora_secret_arn` son
    # obligatorios para el adapter; la contraseña nunca viaja por aquí, se lee
    # del secreto de Secrets Manager (manage_master_user_password).
    aurora_host: str = Field(default="")
    aurora_port: int = Field(default=5432, ge=1, le=65535)
    aurora_dbname: str = Field(default="")
    aurora_username: str = Field(default="chatbot_admin")
    aurora_secret_arn: str = Field(default="")

    @model_validator(mode="after")
    def _bedrock_model_id_es_obligatorio(self) -> Self:
        """Exige modelo de Bedrock antes de arrancar (fail fast).

        Returns:
            La misma instancia, si el modelo vino del entorno.

        Raises:
            ValueError: Si `CHATBOT_BEDROCK_MODEL_ID` falta o está vacío; Pydantic lo
                convierte en `ValidationError` para el llamador.
        """
        if not self.bedrock_model_id:
            raise ValueError(
                "CHATBOT_BEDROCK_MODEL_ID es obligatorio: sin modelo no hay conversación"
            )
        return self


def load_settings() -> Settings:
    """Carga `Settings` desde las variables de entorno del proceso.

    Returns:
        Instancia validada; sin caché para que cada handler pueda recargarla en tests.

    Raises:
        pydantic.ValidationError: Si alguna variable de entorno no es válida.
    """
    return Settings()
