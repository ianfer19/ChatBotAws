"""Cliente HTTP mínimo hacia la Graph API de Meta (tras `GraphApiPort`).

Réplica del `requests.post(...)` de `send_outbound_message`
(`whatsapp_orchestrator_service/app.py:498`) con timeout y traducción de errores:
la Cloud API no es un servicio AWS, así que `boto3` no sirve aquí y se usa `requests`
(misma librería que el legacy). El cliente es inyectable para testear sin red.

Nunca loguea el access token (ni la URL de IG, que lo lleva en query): solo el
código HTTP y el host. El cuerpo de respuesta de Meta se descarta tras leer el
código — los errores se traducen a `ToolError`/`ToolTimeoutError`.
"""

from typing import Protocol, runtime_checkable

import requests
from requests import Response, Session

from shared.errors import ToolError, ToolTimeoutError


@runtime_checkable
class GraphApiPort(Protocol):
    """Subconjunto de HTTP que usa el adapter de canal (DI y dobles de test)."""

    def post(
        self, url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float
    ) -> Response:
        """Envía un POST JSON y devuelve la respuesta cruda.

        Args:
            url: URL completa del endpoint Graph API.
            json: Cuerpo JSON ya construido por el adapter.
            headers: Cabeceras (`Authorization`, `Content-Type`).
            timeout: Segundos de espera de conexión y de respuesta.

        Returns:
            Respuesta de `requests` (el adapter lee `status_code`).

        Raises:
            requests.Timeout: Si Meta no responde a tiempo.
            requests.ConnectionError: Si la red falla.
        """
        ...


class RequestsGraphClient:
    """`GraphApiPort` sobre `requests`, con timeout fijo por llamada.

    Args:
        session: Sesión inyectable (doble de test); `None` usa `requests` real.

    Example:
        >>> from slices.conversation_gateway.infrastructure.channels.http_client import (
        ...     RequestsGraphClient,
        ... )
        >>> RequestsGraphClient().post(
        ...     "https://graph.facebook.com/v24.0/1/messages",
        ...     json={"messaging_product": "whatsapp"},
        ...     headers={"Authorization": "Bearer x"},
        ...     timeout=10,
        ... )  # doctest: +SKIP
    """

    def __init__(self, *, session: Session | None = None) -> None:
        """Guarda la sesión HTTP (real o doble).

        Args:
            session: Sesión `requests` (doble de test); `None` crea la real.
        """
        self._session = session if session is not None else Session()

    def post(
        self, url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float
    ) -> Response:
        """Envía el POST a la Graph API con timeout.

        Args:
            url: URL completa del endpoint.
            json: Cuerpo JSON.
            headers: Cabeceras.
            timeout: Segundos de espera.

        Returns:
            Respuesta cruda de Meta.

        Raises:
            ToolTimeoutError: Si Meta no responde dentro del timeout.
            ToolError: Para cualquier otro fallo de red o HTTP (el original va en
                `__cause__`; jamás se filtra el token ni el stack al usuario).
        """
        try:
            return self._post(url, json=json, headers=headers, timeout=timeout)
        except requests.Timeout as exc:
            raise ToolTimeoutError(
                "timeout de la graph api de meta",
                details={"host": _host_de(url)},
            ) from exc
        except requests.RequestException as exc:
            raise ToolError(
                "fallo de red contra la graph api de meta",
                details={"host": _host_de(url)},
            ) from exc

    def _post(
        self, url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float
    ) -> Response:
        """Despacha a la sesión real o doble (separado para tipar el retorno).

        Args:
            url: URL completa del endpoint.
            json: Cuerpo JSON.
            headers: Cabeceras.
            timeout: Segundos de espera.

        Returns:
            Respuesta cruda (debe ser `Response` en producción).

        Raises:
            requests.RequestException: Si la sesión real falla.
        """
        respuesta = self._session.post(url, json=json, headers=headers, timeout=timeout)
        return respuesta


def _host_de(url: str) -> str:
    """Extrae solo el host de una URL para el log (sin query: IG lleva token ahí).

    Args:
        url: URL completa del endpoint Graph API.

    Returns:
        El host (p. ej. `graph.facebook.com`) o `url` si no se puede parsear.
    """
    try:
        return url.split("/")[2]
    except IndexError:
        return "desconocido"
