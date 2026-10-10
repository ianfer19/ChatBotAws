"""Tests del adapter SSM de credenciales del gateway (Fase 5).

Doble de cliente inyectado (sin AWS real): se verifican las rutas réplica del
legacy (`/sahagun/<canal>/<tenant>/access_token|app_secret`), el
`WithDecryption`/`SecureString`+`Overwrite`, el alias `messenger→facebook` y la
traducción de errores (parámetro ausente ≠ fallo de servicio).
"""

from typing import Any

import pytest
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

from shared.contracts.types import Channel
from shared.errors import ToolError, ToolTimeoutError, ValidationError
from slices.conversation_gateway.domain.errors import CredentialNotFoundError
from slices.conversation_gateway.domain.ports import CredentialsPort
from slices.conversation_gateway.infrastructure.ssm import SsmCredentialStore

_TENANT = "Sede_Elite_01"


def _client_error(codigo: str) -> ClientError:
    """Construye un `ClientError` con el código de negocio indicado.

    Args:
        codigo: Código de error de SSM (p. ej. `ThrottlingException`).

    Returns:
        La excepción tal como la devolvería botocore.
    """
    return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "Operacion")


class _SsmFalso:
    """Doble de `ClienteSSM`: devuelve valores fijos y registra las llamadas."""

    def __init__(
        self,
        *,
        valor: str | None = "tok-valor",
        get_error: Exception | None = None,
        put_error: Exception | None = None,
    ) -> None:
        """Prepara el doble.

        Args:
            valor: Valor que devolverá `get_parameter` (`None` = parámetro ausente).
            get_error: Excepción a lanzar en la lectura.
            put_error: Excepción a lanzar en la escritura.
        """
        self.valor = valor
        self.get_error = get_error
        self.put_error = put_error
        self.gets: list[dict[str, Any]] = []
        self.puts: list[dict[str, Any]] = []

    def get_parameter(self, *, Name: str, WithDecryption: bool = True) -> dict[str, Any]:
        """Registra la lectura y devuelve el valor o el error configurado.

        Args:
            Name: Ruta del parámetro.
            WithDecryption: Debe ser `True` para SecureString.

        Returns:
            `{"Parameter": {"Value": ...}}`.

        Raises:
            Exception: La falla inyectada en el constructor.
        """
        self.gets.append({"Name": Name, "WithDecryption": WithDecryption})
        if self.get_error is not None:
            raise self.get_error
        return {"Parameter": {"Value": self.valor or ""}}

    def put_parameter(
        self,
        *,
        Name: str,
        Value: str,
        Type: str = "SecureString",
        Overwrite: bool = True,
    ) -> dict[str, Any]:
        """Registra la escritura; `None` simula éxito.

        Args:
            Name: Ruta del parámetro.
            Value: Valor secreto (se registra para asserts del test).
            Type: Tipo del parámetro.
            Overwrite: Siempre `True` (alta idempotente).

        Returns:
            Respuesta vacía de éxito.

        Raises:
            Exception: La falla inyectada en el constructor.
        """
        self.puts.append({"Name": Name, "Value": Value, "Type": Type, "Overwrite": Overwrite})
        if self.put_error is not None:
            raise self.put_error
        return {}


def _store(cliente: _SsmFalso) -> SsmCredentialStore:
    """Construye el adapter con el doble de cliente.

    Args:
        cliente: Doble de `ClienteSSM`.

    Returns:
        El `SsmCredentialStore` bajo prueba.
    """
    return SsmCredentialStore(client=cliente)


def test_lee_el_access_token_en_la_ruta_del_legacy() -> None:
    """`/sahagun/whatsapp/<tenant>/access_token` con `WithDecryption=True`."""
    cliente = _SsmFalso(valor="token-secreto")
    token = _store(cliente).get_access_token(channel="whatsapp", tenant_id=_TENANT)
    assert token == "token-secreto"
    assert cliente.gets == [
        {"Name": f"/sahagun/whatsapp/{_TENANT}/access_token", "WithDecryption": True}
    ]


@pytest.mark.parametrize(
    ("channel", "prefijo"),
    [("whatsapp", "whatsapp"), ("instagram", "instagram"), ("messenger", "facebook")],
)
def test_usa_el_prefijo_de_canal_de_las_rutas_del_legacy(*, channel: Channel, prefijo: str) -> None:
    """Messenger hereda el nombre `facebook` de las rutas SSM del legacy."""
    cliente = _SsmFalso()
    _store(cliente).get_access_token(channel=channel, tenant_id=_TENANT)
    assert cliente.gets[0]["Name"] == f"/sahagun/{prefijo}/{_TENANT}/access_token"


def test_parametro_ausente_es_credential_not_found() -> None:
    """Sin parámetro no hay credencial: error propio, no un fallo de servicio."""
    store = _store(_SsmFalso(get_error=_client_error("ParameterNotFound")))
    with pytest.raises(CredentialNotFoundError):
        store.get_access_token(channel="whatsapp", tenant_id=_TENANT)


def test_errores_de_servicio_y_timeout_se_traducen() -> None:
    """Throttling → `ToolError`; timeout de red → `ToolTimeoutError` (ambos reintentables)."""
    fallando = _store(_SsmFalso(get_error=_client_error("ThrottlingException")))
    with pytest.raises(ToolError):
        fallando.get_access_token(channel="whatsapp", tenant_id=_TENANT)
    lento = _store(_SsmFalso(get_error=ConnectTimeoutError(endpoint_url="https://ssm")))
    with pytest.raises(ToolTimeoutError):
        lento.get_access_token(channel="whatsapp", tenant_id=_TENANT)
    lento_lectura = _store(_SsmFalso(get_error=ReadTimeoutError(endpoint_url="https://ssm")))
    with pytest.raises(ToolTimeoutError):
        lento_lectura.get_access_token(channel="whatsapp", tenant_id=_TENANT)


def test_guarda_access_token_como_secure_string_sobrescribiendo() -> None:
    """El alta es idempotente: `SecureString` + `Overwrite=True`, sin tocar la ruta legacy."""
    cliente = _SsmFalso()
    _store(cliente).put_access_token(channel="whatsapp", tenant_id=_TENANT, token="tok-1")
    assert cliente.puts == [
        {
            "Name": f"/sahagun/whatsapp/{_TENANT}/access_token",
            "Value": "tok-1",
            "Type": "SecureString",
            "Overwrite": True,
        }
    ]


def test_guarda_app_secret_en_su_propia_ruta() -> None:
    """`app_secret` vive en su parámetro, junto al token (decisión 2)."""
    cliente = _SsmFalso()
    _store(cliente).put_app_secret(channel="instagram", tenant_id=_TENANT, secret="shh")
    assert cliente.puts[0]["Name"] == f"/sahagun/instagram/{_TENANT}/app_secret"


def test_valores_vacios_o_sin_tenant_son_validation_error() -> None:
    """Un token en blanco es configuración rota; un tenant vacío no es una ruta."""
    store = _store(_SsmFalso())
    with pytest.raises(ValidationError):
        store.put_access_token(channel="whatsapp", tenant_id=_TENANT, token="")
    with pytest.raises(ValidationError):
        store.put_access_token(channel="whatsapp", tenant_id="", token="tok")
    with pytest.raises(ValidationError):
        store.get_access_token(channel="whatsapp", tenant_id="")


def test_errores_de_escritura_se_traducen() -> None:
    """Un fallo al guardar también es `ToolError`/`ToolTimeoutError` tipado."""
    fallando = _store(_SsmFalso(put_error=_client_error("InternalServerError")))
    with pytest.raises(ToolError):
        fallando.put_access_token(channel="whatsapp", tenant_id=_TENANT, token="tok")
    lento = _store(_SsmFalso(put_error=ReadTimeoutError(endpoint_url="https://ssm")))
    with pytest.raises(ToolTimeoutError):
        lento.put_access_token(channel="whatsapp", tenant_id=_TENANT, token="tok")


def test_cumple_credentials_port() -> None:
    """Satisface estructuralmente el port del dominio (DI sin herencia)."""
    assert isinstance(_store(_SsmFalso()), CredentialsPort)


def test_los_secretos_no_aparecen_en_los_logs_del_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regla de logs sin PII: el valor del token jamás se registra (solo la ruta/canal)."""
    from slices.conversation_gateway.infrastructure import ssm as modulo_ssm

    registrados: list[str] = []

    def _registrar(mensaje: str, extra: dict[str, object] | None = None) -> None:
        """Captura el mensaje de log para el assert del test.

        Args:
            mensaje: Mensaje del logger (p. ej. `ssm.credencial_leida`).
            extra: Campos estructurados; no debe contener el valor del token.
        """
        registrados.append(f"{mensaje}:{extra}")

    monkeypatch.setattr(modulo_ssm.logger, "info", _registrar)
    _store(_SsmFalso(valor="valor-secreto")).get_access_token(channel="whatsapp", tenant_id=_TENANT)
    assert registrados
    assert all("valor-secreto" not in linea for linea in registrados)
