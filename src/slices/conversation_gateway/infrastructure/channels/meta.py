"""Adapter `ChannelPort` de Meta sobre los parsers y la Graph API (Fase 6, Commit A).

Único adaptador tras `ChannelPort` (ADR 0009): normaliza la entrada delegando en el
registro `parse_event` de la Fase 3 y envía la respuesta por la Graph API, replicando el
`send_outbound_message` del legacy (`whatsapp_orchestrator_service/app.py:436-505`):
WhatsApp usa la Cloud API (`/{phone_number_id}/messages` con token en header) y
Messenger/Instagram el endpoint `/me/messages` (token en query). Solo texto por hoy
(`OutboundMessage.text`); el envío de media llega con `media_handling` (ROADMAP §4).

Para la recepción basta `normalize_inbound` (constructor sin dependencias); para el
envío se inyectan `api_version`, `http_timeout_seconds`, `credentials` (token en SSM por
tenant+canal, jamás logueado) y `client` (HTTP inyectable). `verify_credentials` solo
comprueba existencia del token (decisión de Fase 5: validar contra Meta queda
`TODO(decision)`).

Errores de envío: `ToolTimeoutError` si Meta no responde a tiempo; `ToolError` si devuelve
>= 400 o la red falla (el consumer lo traduce a reintento de la cola).
"""

from collections.abc import Mapping

from shared.contracts.messages import OutboundMessage
from shared.contracts.types import Channel
from shared.errors import ToolError, ValidationError
from shared.logging import get_logger
from shared.ports import ChannelMessage
from slices.conversation_gateway.domain.errors import CredentialNotFoundError
from slices.conversation_gateway.domain.ports import CredentialsPort
from slices.conversation_gateway.infrastructure.channels import parse_event
from slices.conversation_gateway.infrastructure.channels.http_client import GraphApiPort

logger = get_logger(__name__)

_BASES: dict[Channel, str] = {
    "whatsapp": "https://graph.facebook.com",
    "messenger": "https://graph.facebook.com",
    "instagram": "https://graph.instagram.com",
}
# Réplica del `base_url` del legacy (app.py:442): Instagram vive en su propio host.


class MetaChannel:
    """`ChannelPort` de Meta: normaliza la entrada y envía la salida por Graph API.

    Args:
        api_version: Versión de la Graph API (`v24.0`, del `Settings`); solo para
            envío. `None` = solo recepción (constructor del webhook).
        http_timeout_seconds: Timeout del HTTP hacia Meta; solo para envío.
        credentials: Lector de access token por tenant+canal (`SsmCredentialStore`);
            solo para envío.
        client: Cliente HTTP inyectable (doble de test); solo para envío.

    Example:
        >>> from slices.conversation_gateway.infrastructure.channels.meta import MetaChannel
        >>> MetaChannel().normalize_inbound({"entry": []}, channel="whatsapp")
        []
    """

    def __init__(
        self,
        *,
        api_version: str | None = None,
        http_timeout_seconds: int | None = None,
        credentials: CredentialsPort | None = None,
        client: GraphApiPort | None = None,
    ) -> None:
        """Guarda la configuración de envío (todas opcionales: recepción sin más).

        Args:
            api_version: Versión de la Graph API (p. ej. `v24.0`).
            http_timeout_seconds: Segundos de espera del HTTP.
            credentials: Adaptador de access token por tenant+canal.
            client: Cliente HTTP (real o doble).

        Raises:
            ValidationError: Si el timeout es < 1 (fail fast; `None` = sin envío).
        """
        if http_timeout_seconds is not None and http_timeout_seconds < 1:
            raise ValidationError("meta_http_timeout_seconds debe ser >= 1")
        self._version = api_version
        self._timeout = float(http_timeout_seconds) if http_timeout_seconds else None
        self._credentials = credentials
        self._client = client

    def normalize_inbound(
        self, payload: Mapping[str, object], *, channel: Channel
    ) -> list[ChannelMessage]:
        """Interpreta el payload con el parser del canal detectado.

        Args:
            payload: JSON ya parseado del webhook (cuerpo exacto de Meta).
            channel: Canal detectado en el envelope (`detect_channel`).

        Returns:
            Los mensajes normalizados en orden; vacía si el evento se ignora
            (estados de lectura, ecos o reacciones).

        Raises:
            ValidationError: Si el payload no es del formato esperado del canal.
        """
        return parse_event(payload, channel=channel)

    def send(self, message: OutboundMessage) -> None:
        """Envía la respuesta de texto al cliente por el canal del mensaje.

        Args:
            message: Respuesta ya redactada, con `tenant_id`, `channel`,
                `emitter_id` (recipient_id), `customer_id` y `text`.

        Returns:
            None si Meta aceptó el mensaje (HTTP < 400).

        Raises:
            ToolError: Si no hay credenciales/HTTP inyectados, falta `emitter_id` o
                Meta devuelve >= 400 (el consumer reintenta el mensaje de la cola).
            ToolTimeoutError: Si Meta no responde dentro del timeout.
        """
        if self._credentials is None or self._client is None or self._version is None:
            raise ToolError(
                "canal sin dependencias de envio (inyectar credentials/client/api_version)",
                details={"tenant_id": message.tenant_id, "channel": message.channel},
            )
        token = self._credentials.get_access_token(
            channel=message.channel, tenant_id=message.tenant_id
        )
        url, payload, headers = self._construir(message, token)
        respuesta = self._client.post(
            url, json=payload, headers=headers, timeout=self._timeout or 10.0
        )
        if respuesta.status_code >= 400:
            # Nunca loguear el token ni el body completo (lleva PII).
            logger.error(
                "meta.envio_rechazado",
                extra={
                    "tenant_id": message.tenant_id,
                    "channel": message.channel,
                    "status": respuesta.status_code,
                },
            )
            raise ToolError(
                "meta rechazo el mensaje saliente",
                details={
                    "tenant_id": message.tenant_id,
                    "status": str(respuesta.status_code),
                },
            )
        logger.info(
            "meta.envio_ok",
            extra={"tenant_id": message.tenant_id, "channel": message.channel},
        )

    def verify_credentials(self, *, channel: Channel, tenant_id: str) -> bool:
        """Comprueba que el comercio tiene access token para ese canal (Fase 5).

        Args:
            channel: Canal consultado.
            tenant_id: Comercio consultado.

        Returns:
            `True` si el token existe; `False` si falta.
        """
        if self._credentials is None:
            return False
        try:
            self._credentials.get_access_token(channel=channel, tenant_id=tenant_id)
        except (CredentialNotFoundError, ToolError):
            return False
        return True

    def _construir(
        self, message: OutboundMessage, token: str
    ) -> tuple[str, dict[str, object], dict[str, str]]:
        """Construye URL, payload y headers según el canal (réplica del legacy).

        Args:
            message: Mensaje saliente.
            token: Access token del comercio (no se registra).

        Returns:
            Tupla `(url, payload, headers)`.

        Raises:
            ToolError: Si falta `emitter_id` (no hay a quién responder).
        """
        if not message.emitter_id:
            raise ToolError(
                "mensaje saliente sin emitter_id (recipient_id)",
                details={"tenant_id": message.tenant_id, "channel": message.channel},
            )
        base = _BASES[message.channel]
        version = self._version or ""
        if message.channel == "whatsapp":
            url = f"{base}/{version}/{message.emitter_id}/messages"
            payload: dict[str, object] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": message.customer_id,
                "type": "text",
                "text": {"body": message.text},
            }
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            return (url, payload, headers)
        # Messenger / Instagram: token en query (app.py:472-496).
        url = f"{base}/{version}/me/messages"
        payload = {
            "recipient": {"id": message.customer_id},
            "message": {"text": message.text},
        }
        return (url, payload, {"Authorization": f"Bearer {token}"})
