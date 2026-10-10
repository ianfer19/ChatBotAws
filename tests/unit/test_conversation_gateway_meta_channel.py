"""Tests de la Fase 6 Commit A: envío de respuestas por la Graph API (`MetaChannel.send`).

Replica los casos del `send_outbound_message` del legacy sin red: el doble de Graph
API (`InMemoryGraphClient`) captura el POST y devuelve un `status_code` fijo, y el doble
de credenciales (`InMemoryCredentialStore`) sirve el token por tenant+canal. Se verifica
la forma de la petición (URL, payload, cabeceras) por canal y las traducciones de error
(`ToolError` a >= 400; `ToolTimeoutError` viaja desde el cliente HTTP).
"""

import pytest

from shared.contracts.messages import OutboundMessage
from shared.contracts.types import Channel
from shared.errors import ToolError
from shared.ports import ChannelPort
from slices.conversation_gateway.domain.errors import CredentialNotFoundError
from slices.conversation_gateway.infrastructure.channels.meta import MetaChannel
from slices.conversation_gateway.infrastructure.in_memory import (
    InMemoryCredentialStore,
    InMemoryGraphClient,
)

_TENANT = "Sede_Elite_01"
_EMISOR = "1000"
_CLIENTE = "57300111111"


def _store() -> InMemoryCredentialStore:
    """Credenciales de prueba para los 3 canales.

    Returns:
        Doble con un access token por canal para el tenant de prueba.
    """
    store = InMemoryCredentialStore()
    canales: list[Channel] = ["whatsapp", "messenger", "instagram"]
    for canal in canales:
        store.put_access_token(channel=canal, tenant_id=_TENANT, token="tok-123")
    return store


def _outbound(canal: Channel = "whatsapp") -> OutboundMessage:
    """Respuesta saliente de prueba hacia el cliente.

    Args:
        canal: Canal por el que se responde.

    Returns:
        `OutboundMessage` con el emisor (recipient_id) y el texto fijos.
    """
    return OutboundMessage(
        tenant_id=_TENANT,
        correlation_id="corr-1",
        channel=canal,
        emitter_id=_EMISOR,
        customer_id=_CLIENTE,
        text="hola",
    )


def _canal(cliente: InMemoryGraphClient) -> MetaChannel:
    """MetaChannel con el doble de Graph API y credenciales de prueba.

    Args:
        cliente: Doble de Graph API que capturará el POST.

    Returns:
        Adaptador listo para `send`.
    """
    return MetaChannel(
        api_version="v24.0",
        http_timeout_seconds=10,
        credentials=_store(),
        client=cliente,
    )


def test_meta_channel_cumple_channel_port_completo() -> None:
    """El adaptador real satisface el `ChannelPort` completo (recepción y envío)."""
    assert isinstance(MetaChannel(), ChannelPort)


def test_envio_whatsapp_usa_cloud_api_con_token_en_header() -> None:
    """WhatsApp envía a `/v24.0/<phone_number_id>/messages` con el token en `Authorization`."""
    cliente = InMemoryGraphClient()
    _canal(cliente).send(_outbound("whatsapp"))
    (llamada,) = cliente.calls
    assert llamada.url == "https://graph.facebook.com/v24.0/1000/messages"
    payload = llamada.json
    assert payload["messaging_product"] == "whatsapp"
    assert payload["recipient_type"] == "individual"
    assert payload["to"] == _CLIENTE
    assert payload["type"] == "text"
    assert payload["text"] == {"body": "hola"}
    assert llamada.headers["Authorization"] == "Bearer tok-123"


def test_envio_messenger_usa_me_messages_con_token_en_header() -> None:
    """Messenger envía a `/me/messages` (token en cabecera, host de Facebook)."""
    cliente = InMemoryGraphClient()
    _canal(cliente).send(_outbound("messenger"))
    (llamada,) = cliente.calls
    assert llamada.url == "https://graph.facebook.com/v24.0/me/messages"
    assert llamada.json["recipient"] == {"id": _CLIENTE}
    assert llamada.json["message"] == {"text": "hola"}
    assert llamada.headers["Authorization"] == "Bearer tok-123"


def test_envio_instagram_usa_su_propio_host() -> None:
    """Instagram vive en `graph.instagram.com` (réplica del `base_url` del legacy)."""
    cliente = InMemoryGraphClient()
    _canal(cliente).send(_outbound("instagram"))
    (llamada,) = cliente.calls
    assert llamada.url == "https://graph.instagram.com/v24.0/me/messages"


def test_envio_usa_el_timeout_configurado() -> None:
    """El timeout hacia Meta sale de `meta_http_timeout_seconds` (no del de Bedrock)."""
    cliente = InMemoryGraphClient()
    _canal(cliente).send(_outbound("whatsapp"))
    assert cliente.calls[0].timeout == 10.0


def test_rechazo_de_meta_se_traduce_a_tool_error() -> None:
    """Un `status_code` >= 400 de Graph API se traduce a `ToolError` (reintento de cola)."""
    cliente = InMemoryGraphClient(status_code=400)
    with pytest.raises(ToolError):
        _canal(cliente).send(_outbound("whatsapp"))


def test_envio_sin_token_falla_sin_llegar_a_la_red() -> None:
    """Un comercio sin credenciales no llega a la red: `CredentialNotFoundError` del dominio.

    El adaptador NO la envuelve en `ToolError`: la deja propagar para que quien la
    captura (handler/consumer) decida el mapeo HTTP (502 interno, nunca al usuario).
    """
    store = InMemoryCredentialStore()
    canal = MetaChannel(
        api_version="v24.0",
        http_timeout_seconds=10,
        credentials=store,
        client=InMemoryGraphClient(),
    )
    with pytest.raises(CredentialNotFoundError):
        canal.send(_outbound("whatsapp"))


def test_envio_sin_credenciales_inyectadas_es_tool_error() -> None:
    """Un `MetaChannel` solo-recepción no puede enviar: falla rápido sin tocar la red."""
    canal = MetaChannel()
    with pytest.raises(ToolError):
        canal.send(_outbound("whatsapp"))


def test_verify_credentials_refleja_existencia_del_token() -> None:
    """`verify_credentials` devuelve `True`/`False` según el token en SSM (Fase 5)."""
    canal = _canal(InMemoryGraphClient())
    assert canal.verify_credentials(channel="whatsapp", tenant_id=_TENANT) is True
    assert canal.verify_credentials(channel="whatsapp", tenant_id="Otro_Tenant") is False
