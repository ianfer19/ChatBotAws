"""Adapters de canal tras ChannelPort: parsers de payload (Fase 3) y registro común.

Cada canal tiene su paquete (`whatsapp/`, `instagram/`, `messenger/`) con su parser;
el cliente de envío y `verify_credentials` viven en `MetaChannel` de `meta.py` (Fase 6),
que comparte Graph API y credenciales SSM entre los 3 canales (ADR 0009: añadir canal =
parser nuevo + registro aquí, sin tocar dominio ni grafo). Solo envío y recepción, sin
reglas de negocio.
"""

from collections.abc import Callable, Mapping

from shared.contracts.types import Channel
from shared.ports import ChannelMessage
from slices.conversation_gateway.infrastructure.channels.instagram.parser import (
    parse as parse_instagram,
)
from slices.conversation_gateway.infrastructure.channels.messenger.parser import (
    parse as parse_messenger,
)
from slices.conversation_gateway.infrastructure.channels.whatsapp.parser import (
    parse as parse_whatsapp,
)

Parser = Callable[[Mapping[str, object]], list[ChannelMessage]]
# Firma de un parser de canal: payload crudo ya parseado → mensajes normalizados.

_PARSERS: dict[Channel, Parser] = {
    "whatsapp": parse_whatsapp,
    "instagram": parse_instagram,
    "messenger": parse_messenger,
}


def parse_event(payload: Mapping[str, object], *, channel: Channel) -> list[ChannelMessage]:
    """Despacha el payload al parser del canal detectado (`detect_channel`).

    Args:
        payload: JSON del webhook.
        channel: Canal detectado en el envelope.

    Returns:
        Los mensajes normalizados en orden; vacía = evento a ignorar (200 sin
        reprocesar).

    Raises:
        ValidationError: Si el payload no cumple el formato del canal.
    """
    return _PARSERS[channel](payload)
