"""Adapter de SSM SecureString: credenciales por comercio del gateway (Fase 5).

Réplica de la ruta del legacy (`whatsapp_orchestrator_service/app.py:293`):
`/sahagun/<canal>/<tenant_id>/access_token|app_secret`, con `WithDecryption` al
leer y `Type=SecureString` + `Overwrite` al escribir. Los valores son secretos:
nunca se loguean ni se devuelven fuera del adaptador (solo el consumer de envíos
los usa para firmar las llamadas a Meta). Los clientes son inyectables para
testear sin AWS.
"""

from collections.abc import Mapping
from typing import Any, Protocol, cast, runtime_checkable

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

from shared.contracts.types import Channel
from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.logging import get_logger
from slices.conversation_gateway.domain.errors import CredentialNotFoundError

logger = get_logger(__name__)

_SSM_SERVICE = "ssm"
_NOMBRE_ACCESS_TOKEN = "access_token"
_NOMBRE_APP_SECRET = "app_secret"
_TIPO_SECURE_STRING = "SecureString"
# SSM devuelve el parámetro inexistente como `ClientError` con este código (no
# hay excepción propia en `botocore.exceptions`; `TODO(verify)` contra la doc de
# la API de SSM si cambia).
_CODIGO_PARAMETRO_AUSENTE = "ParameterNotFound"
# El legacy llama "facebook" al canal Messenger en sus rutas SSM
# (`resolved_platform`); se conserva la compatibilidad con los parámetros ya
# creados. TODO(verify): confirmar los nombres reales de los parámetros en AWS.
_PREFIJOS_CANAL: Mapping[Channel, str] = {
    "whatsapp": "whatsapp",
    "instagram": "instagram",
    "messenger": "facebook",
}


@runtime_checkable
class ClienteSSM(Protocol):
    """Subconjunto de `ssm` que usa este adapter (DI y dobles de test)."""

    def get_parameter(self, *, Name: str, WithDecryption: bool = ...) -> dict[str, Any]:
        """Lee un parámetro por nombre.

        Args:
            Name: Ruta completa del parámetro.
            WithDecryption: `True` para SecureString.

        Returns:
            Diccionario con `Parameter.Value`.

        Raises:
            ClientError: Con código `ParameterNotFound` si el parámetro no existe,
                u otro error de negocio del servicio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...

    def put_parameter(
        self,
        *,
        Name: str,
        Value: str,
        Type: str = ...,
        Overwrite: bool = ...,
    ) -> dict[str, Any]:
        """Escribe (o sobrescribe) un parámetro.

        Args:
            Name: Ruta completa del parámetro.
            Value: Valor secreto (no se registra).
            Type: Siempre `SecureString`.
            Overwrite: `True` para que la alta sea idempotente.

        Returns:
            Respuesta del servicio.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


def _cliente_real(timeout_seconds: int) -> ClienteSSM:
    """Crea el cliente `ssm` con timeout y reintentos limitados.

    Args:
        timeout_seconds: Segundos de espera de conexión y de operación.

    Returns:
        Cliente listo para `get_parameter`/`put_parameter`.

    TODO(verify): número de reintentos y parámetros de `Config`, verificados
    contra la doc de botocore (mismo criterio que `DynamoChannelMapping`).
    """
    config = Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    # boto3 no tiene stubs: la anotación es la que garantiza la firma del protocolo.
    cliente: ClienteSSM = boto3.client(_SSM_SERVICE, config=config)
    return cliente


def _ruta(*, channel: Channel, tenant_id: str, nombre: str) -> str:
    """Compone la ruta del parámetro réplica del legacy.

    Args:
        channel: Canal de Meta.
        tenant_id: Comercio dueño.
        nombre: `access_token` o `app_secret`.

    Returns:
        La ruta `/sahagun/<canal>/<tenant>/<nombre>`.
    """
    return f"/sahagun/{_PREFIJOS_CANAL[channel]}/{tenant_id}/{nombre}"


def _es_parametro_ausente(exc: Exception) -> bool:
    """Detecta el `ClientError` de SSM para un parámetro inexistente.

    Args:
        exc: Excepción capturada del cliente.

    Returns:
        `True` solo para el código `ParameterNotFound`.
    """
    if not isinstance(exc, ClientError):
        return False
    error = cast(ClientError, exc)
    return str(error.response.get("Error", {}).get("Code")) == _CODIGO_PARAMETRO_AUSENTE


class SsmCredentialStore:
    """`CredentialsPort` sobre SSM SecureString (rutas réplica del legacy).

    Args:
        timeout_seconds: Timeout de conexión y de operación.
        client: Cliente inyectable (doble de test); `None` crea el real con boto3.

    Example:
        >>> from unittest.mock import MagicMock
        >>> from slices.conversation_gateway.infrastructure.ssm import SsmCredentialStore
        >>> cliente = MagicMock()
        >>> cliente.get_parameter.return_value = {"Parameter": {"Value": "tok"}}
        >>> store = SsmCredentialStore(client=cliente)
        >>> store.get_access_token(channel="whatsapp", tenant_id="Sede_Elite_01")
        'tok'
    """

    def __init__(self, *, timeout_seconds: int = 5, client: ClienteSSM | None = None) -> None:
        self._client = client if client is not None else _cliente_real(timeout_seconds)

    def get_access_token(self, *, channel: Channel, tenant_id: str) -> str:
        """Lee el access token del comercio (SecureString).

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.

        Returns:
            El token guardado.

        Raises:
            ValidationError: Si falta `tenant_id`.
            CredentialNotFoundError: Si el parámetro no existe.
            ToolError: Si SSM rechaza u otro fallo (el original en `__cause__`).
            ToolTimeoutError: Si la lectura excede el timeout.
        """
        return self._leer(channel=channel, tenant_id=tenant_id, nombre=_NOMBRE_ACCESS_TOKEN)

    def put_access_token(self, *, channel: Channel, tenant_id: str, token: str) -> None:
        """Guarda (o sobrescribe) el access token del comercio.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            token: Valor del token (no se registra).

        Returns:
            None.

        Raises:
            ValidationError: Si falta `tenant_id` o `token`.
            ToolError: Si SSM rechaza la escritura.
            ToolTimeoutError: Si la escritura excede el timeout.
        """
        self._escribir(
            channel=channel, tenant_id=tenant_id, nombre=_NOMBRE_ACCESS_TOKEN, valor=token
        )

    def put_app_secret(self, *, channel: Channel, tenant_id: str, secret: str) -> None:
        """Guarda (o sobrescribe) el app secret del comercio.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            secret: Valor del secreto (no se registra).

        Returns:
            None.

        Raises:
            ValidationError: Si falta `tenant_id` o `secret`.
            ToolError: Si SSM rechaza la escritura.
            ToolTimeoutError: Si la escritura excede el timeout.
        """
        self._escribir(
            channel=channel, tenant_id=tenant_id, nombre=_NOMBRE_APP_SECRET, valor=secret
        )

    def _leer(self, *, channel: Channel, tenant_id: str, nombre: str) -> str:
        """Lee un parámetro y traduce sus errores.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            nombre: Nombre del parámetro (`access_token`/`app_secret`).

        Returns:
            El valor del parámetro.

        Raises:
            ValidationError: Si falta `tenant_id`.
            CredentialNotFoundError: Si el parámetro no existe.
            ToolError/ToolTimeoutError: Si SSM falla.
        """
        if not tenant_id:
            raise ValidationError("tenant_id vacio al leer credenciales de ssm")
        ruta = _ruta(channel=channel, tenant_id=tenant_id, nombre=nombre)
        try:
            respuesta = self._client.get_parameter(Name=ruta, WithDecryption=True)
        except (ConnectTimeoutError, ReadTimeoutError) as exc:
            raise ToolTimeoutError(
                "timeout de ssm al leer credenciales",
                details={"channel": channel, "tenant_id": tenant_id},
            ) from exc
        except (BotoCoreError, ClientError) as exc:
            if _es_parametro_ausente(exc):
                raise CredentialNotFoundError(
                    "credencial ausente en ssm",
                    details={"channel": channel, "tenant_id": tenant_id, "parametro": nombre},
                ) from exc
            raise ToolError(
                "ssm rechazo la lectura de credenciales",
                details={"channel": channel, "tenant_id": tenant_id},
            ) from exc
        valor = str(respuesta.get("Parameter", {}).get("Value", ""))
        logger.info(
            "ssm.credencial_leida",
            extra={"channel": channel, "tenant_id": tenant_id, "parametro": nombre},
        )
        return valor

    def _escribir(self, *, channel: Channel, tenant_id: str, nombre: str, valor: str) -> None:
        """Escribe un parámetro SecureString y traduce sus errores.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            nombre: Nombre del parámetro.
            valor: Valor secreto (no se registra en ningún log).

        Returns:
            None.

        Raises:
            ValidationError: Si falta `tenant_id` o el valor.
            ToolError/ToolTimeoutError: Si SSM falla.
        """
        if not tenant_id or not valor:
            raise ValidationError("faltan tenant_id o valor en la credencial de ssm")
        ruta = _ruta(channel=channel, tenant_id=tenant_id, nombre=nombre)
        try:
            self._client.put_parameter(
                Name=ruta,
                Value=valor,
                Type=_TIPO_SECURE_STRING,
                Overwrite=True,
            )
        except (ConnectTimeoutError, ReadTimeoutError) as exc:
            raise ToolTimeoutError(
                "timeout de ssm al guardar credenciales",
                details={"channel": channel, "tenant_id": tenant_id},
            ) from exc
        except (BotoCoreError, ClientError) as exc:
            raise ToolError(
                "ssm rechazo el guardado de credenciales",
                details={"channel": channel, "tenant_id": tenant_id},
            ) from exc
        logger.info(
            "ssm.credencial_guardada",
            extra={"channel": channel, "tenant_id": tenant_id, "parametro": nombre},
        )
