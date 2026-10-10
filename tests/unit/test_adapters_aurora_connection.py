"""Tests unitarios de `AuroraConnectionFactory`: secreto, caché y configuración.

Sin Secrets Manager real: un doble de cliente y `psycopg.connect` monkeypacheado
verifican que la contraseña se lee una sola vez, no viaja por el repo y que una
configuración incompleta no arranca.
"""

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

import adapters.aurora.connection as connection_module
from adapters.aurora import AuroraConnectionFactory
from shared.config import Settings
from shared.errors import ToolError, ValidationError

_HOST = "chatbot-aws-dev.cluster-abc.us-east-1.rds.amazonaws.com"
_DBNAME = "chatbot"
_USERNAME = "chatbot_admin"
_SECRET = "arn:aws:secretsmanager:us-east-1:029944900353:secret:aurora-master"


class _SecretsFalso:
    """Doble de Secrets Manager que registra las lecturas del secreto."""

    def __init__(
        self,
        secreto: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Prepara el secreto o el error que devolverá.

        Args:
            secreto: JSON del secreto (claves `username`/`password`).
            error: Excepción a lanzar en `get_secret_value`.
        """
        self.llamadas: list[str] = []
        self._secreto = secreto if secreto is not None else {"password": "secreta"}
        self._error = error

    def get_secret_value(self, *, SecretId: str) -> dict[str, Any]:
        """Registra el ARN pedido y devuelve el secreto configurado."""
        self.llamadas.append(SecretId)
        if self._error is not None:
            raise self._error
        return {"SecretString": json.dumps(self._secreto)}


def _fabrica(**sobrescribir: Any) -> tuple[AuroraConnectionFactory, _SecretsFalso]:
    """Fábrica con secreto y `psycopg.connect` de prueba.

    Args:
        sobrescribir: Campos a sobreescribir del constructor.

    Returns:
        Tupla `(fábrica, doble de secretos)`.
    """
    secrets = _SecretsFalso()
    campos: dict[str, Any] = {
        "host": _HOST,
        "dbname": _DBNAME,
        "username": _USERNAME,
        "secret_arn": _SECRET,
        "secrets_client": secrets,
    }
    campos.update(sobrescribir)
    return AuroraConnectionFactory(**campos), secrets


def _instalafalso(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Monkeypachea `psycopg.connect` registrando los kwargs de cada conexión.

    Args:
        monkeypatch: Fixtures de pytest.

    Returns:
        Lista que se rellena con los kwargs de cada conexión abierta.
    """
    abiertas: list[dict[str, Any]] = []

    def _connect(**kwargs: Any) -> object:
        abiertas.append(kwargs)
        return object()

    monkeypatch.setattr(connection_module.psycopg, "connect", _connect)
    return abiertas


def test_configuracion_incompleta_es_validation_error() -> None:
    """Sin host, base o ARN de secreto la fábrica no arranca (fail fast)."""
    with pytest.raises(ValidationError):
        AuroraConnectionFactory(host="", dbname=_DBNAME, username=_USERNAME, secret_arn=_SECRET)
    with pytest.raises(ValidationError):
        AuroraConnectionFactory(host=_HOST, dbname="", username=_USERNAME, secret_arn=_SECRET)
    with pytest.raises(ValidationError):
        AuroraConnectionFactory(host=_HOST, dbname=_DBNAME, username=_USERNAME, secret_arn="")


def test_from_settings_mapea_los_campos_de_aurora(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CHATBOT_AURORA_*` de `Settings` llegan a la conexión psycopg."""
    abiertas = _instalafalso(monkeypatch)
    secrets = _SecretsFalso()

    def _falso_cliente(servicio: str) -> _SecretsFalso:
        """Doble del cliente Secrets Manager (el servicio se ignora en el test)."""
        return secrets

    monkeypatch.setattr(connection_module.boto3, "client", _falso_cliente)
    settings = Settings(
        bedrock_model_id="modelo",
        aurora_host=_HOST,
        aurora_dbname=_DBNAME,
        aurora_secret_arn=_SECRET,
    )
    AuroraConnectionFactory.from_settings(settings)()
    assert abiertas[0]["host"] == _HOST
    assert abiertas[0]["dbname"] == _DBNAME
    assert abiertas[0]["user"] == "chatbot_admin"
    assert abiertas[0]["port"] == 5432


def test_lee_el_password_del_secreto_y_lo_cachea(monkeypatch: pytest.MonkeyPatch) -> None:
    """La contraseña se pide a Secrets Manager solo en la primera conexión."""
    abiertas = _instalafalso(monkeypatch)
    fabrica, secrets = _fabrica()

    fabrica()
    fabrica()

    assert secrets.llamadas == [_SECRET]
    assert len(abiertas) == 2
    assert abiertas[0]["password"] == "secreta"
    assert abiertas[0]["host"] == _HOST
    assert abiertas[0]["user"] == _USERNAME
    assert abiertas[0]["dbname"] == _DBNAME
    assert abiertas[0]["autocommit"] is True


def test_secreto_sin_password_es_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un secreto mal formado no se convierte en una conexión con contraseña vacía."""
    _instalafalso(monkeypatch)
    fabrica, _ = _fabrica(secrets_client=_SecretsFalso(secreto={"username": "admin"}))
    with pytest.raises(ToolError):
        fabrica()


def test_error_de_secrets_manager_es_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ClientError` de Secrets Manager se traduce a `ToolError` tipado."""
    _instalafalso(monkeypatch)
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}, "ResponseMetadata": {}},
        "GetSecretValue",
    )
    fabrica, _ = _fabrica(secrets_client=_SecretsFalso(error=error))
    with pytest.raises(ToolError):
        fabrica()


def test_timeout_de_conexion_invalido_es_validation_error() -> None:
    """Un timeout de conexión no positivo se rechaza al construir."""
    with pytest.raises(ValidationError):
        AuroraConnectionFactory(
            host=_HOST,
            dbname=_DBNAME,
            username=_USERNAME,
            secret_arn=_SECRET,
            connect_timeout_seconds=0,
        )
