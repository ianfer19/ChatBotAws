"""Conexión a Aurora PostgreSQL para los adapters del RAG (Paso 7).

`AuroraConnectionFactory` abre conexiones `psycopg` con la contraseña leída (y
cacheada) del secreto de Secrets Manager que gestiona el propio clúster
(`manage_master_user_password`); la contraseña jamás viaja por variables de
entorno ni por el repo. Siempre `autocommit`: cada operación del adapter es una
sentencia corta y no necesita transacción larga.

`TODO(verify)`: claves exactas del JSON del secreto gestionado por AWS
(`username`/`password`), `statement_timeout` por sentencia y si conviene un pool
de conexiones cuando las Lambdas crezcan.
"""

import json
from collections.abc import Callable
from typing import Any

import boto3
import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from psycopg import Connection

from shared.config import Settings
from shared.errors import ToolError, ValidationError
from shared.logging import get_logger

_logger = get_logger(__name__)

_CONNECT_TIMEOUT_SECONDS = 10
"""Segundos máximos de conexión al clúster (`TODO(verify)` con carga real)."""


class AuroraConnectionFactory:
    """Fábrica de conexiones psycopg con la contraseña de Secrets Manager.

    La fábrica es invocable (`factory()` → conexión nueva) para que los adapters
    inyecten `Callable[[], Connection]` y los tests inyecten su doble.

    Example:
        >>> AuroraConnectionFactory(
        ...     host="", dbname="", username="chatbot_admin", secret_arn=""
        ... )
        Traceback (most recent call last):
            ...
        shared.errors.ValidationError: configuración de Aurora incompleta...
    """

    def __init__(
        self,
        *,
        host: str,
        dbname: str,
        username: str,
        secret_arn: str,
        port: int = 5432,
        connect_timeout_seconds: int = _CONNECT_TIMEOUT_SECONDS,
        secrets_client: Any | None = None,
    ) -> None:
        """Valida la configuración y prepara la lectura perezosa del secreto.

        Args:
            host: Endpoint del clúster (output `aurora_endpoint` del stack).
            dbname: Nombre de la base de datos.
            username: Usuario master (no se lee del secreto: lo fija el stack).
            secret_arn: ARN del secreto con la contraseña del master.
            port: Puerto PostgreSQL (5432 por defecto).
            connect_timeout_seconds: Segundos máximos para abrir conexión.
            secrets_client: Cliente Secrets Manager a inyectar en tests; si es
                `None` se crea el real.

        Raises:
            ValidationError: Si falta host, base, usuario o ARN del secreto, o
                si los tiempos no son positivos.
        """
        if not host or not dbname or not username or not secret_arn:
            raise ValidationError(
                "configuración de Aurora incompleta: define CHATBOT_AURORA_HOST, "
                "CHATBOT_AURORA_DBNAME y CHATBOT_AURORA_SECRET_ARN",
                details={"host": host, "dbname": dbname, "secret_arn": secret_arn},
            )
        if connect_timeout_seconds < 1:
            raise ValidationError(
                "timeout de conexión inválido para Aurora",
                details={"connect_timeout_seconds": str(connect_timeout_seconds)},
            )
        self._host = host
        self._port = port
        self._dbname = dbname
        self._username = username
        self._secret_arn = secret_arn
        self._connect_timeout_seconds = connect_timeout_seconds
        self._secrets_client = secrets_client
        self._password: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "AuroraConnectionFactory":
        """Construye la fábrica desde `Settings` (cliente de secretos real).

        Args:
            settings: Ajustes del proceso (`CHATBOT_AURORA_*`).

        Returns:
            Fábrica validada; la contraseña se lee al primer `call`.
        """
        return cls(
            host=settings.aurora_host,
            port=settings.aurora_port,
            dbname=settings.aurora_dbname,
            username=settings.aurora_username,
            secret_arn=settings.aurora_secret_arn,
        )

    def __call__(self) -> Connection[tuple[Any, ...]]:
        """Abre una conexión nueva al clúster (autocommit).

        Returns:
            Conexión `psycopg` lista para usar; el caller la cierra siempre.

        Raises:
            ToolError: Si el secreto no se puede leer o no trae contraseña.
            psycopg.Error: Si la conexión falla (la traduce cada adapter).
        """
        return psycopg.connect(
            host=self._host,
            port=self._port,
            dbname=self._dbname,
            user=self._username,
            password=self._password_obtenida(),
            connect_timeout=self._connect_timeout_seconds,
            autocommit=True,
        )

    def _password_obtenida(self) -> str:
        """Devuelve la contraseña, leyéndola del secreto solo la primera vez.

        Returns:
            La contraseña del master; caché en la instancia (no global).

        Raises:
            ToolError: Si Secrets Manager falla o el secreto no trae contraseña.
        """
        if self._password is None:
            self._password = self._leer_secreto()
            _logger.info(
                "aurora.secreto_cargado",
                extra={"secret_arn": self._secret_arn},
            )
        return self._password

    def _leer_secreto(self) -> str:
        """Lee la contraseña del secreto de Secrets Manager.

        Returns:
            El campo `password` del JSON del secreto.

        Raises:
            ToolError: Si la llamada falla, si el JSON es inválido o si el
                campo `password` falta o está vacío.
        """
        cliente = self._secrets_client
        try:
            if cliente is None:
                # También dentro del try: crear el cliente puede fallar (p. ej.
                # sin región configurada) y ese fallo debe salir tipado.
                cliente = boto3.client("secretsmanager")
            respuesta = cliente.get_secret_value(SecretId=self._secret_arn)
            secreto = json.loads(respuesta["SecretString"])
        except (ClientError, BotoCoreError) as exc:
            _logger.error(
                "aurora.secreto_fallido",
                extra={"secret_arn": self._secret_arn, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudo leer el secreto de Aurora",
                details={"secret_arn": self._secret_arn},
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolError(
                "secreto de Aurora con forma inesperada",
                details={"secret_arn": self._secret_arn},
            ) from exc
        password = secreto.get("password") if isinstance(secreto, dict) else None
        if not isinstance(password, str) or not password:
            raise ToolError(
                "secreto de Aurora sin contraseña",
                details={"secret_arn": self._secret_arn},
            )
        return password


ConnectionFactory = Callable[[], Connection[tuple[Any, ...]]]
"""Tipo inyectable: una fábrica de conexiones (la real o un doble de test)."""
