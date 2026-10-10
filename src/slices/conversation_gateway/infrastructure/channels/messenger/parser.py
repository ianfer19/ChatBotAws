"""Parser del webhook de Messenger → lista de `ChannelMessage` (Fase 3).

Envelope de Graph API (`entry[].messaging[]`) compartido con Instagram: la parte
propia de Facebook es el adjunto `location` con `coordinates.lat/long`, que este
canal sí interpreta (legacy `facebook_adapter`). Los ecos, `delivery`/`read` y
otros eventos sin `message` se descartan.
"""

from collections.abc import Mapping

from shared.contracts.types import Channel
from shared.ports import ChannelMessage
from slices.conversation_gateway.infrastructure.channels.messaging import parse_messaging

_CANAL: Channel = "messenger"


def parse(payload: Mapping[str, object]) -> list[ChannelMessage]:
    """Normaliza todos los mensajes del envelope de Messenger.

    Args:
        payload: JSON del webhook (`entry[].messaging[]`).

    Returns:
        Un `ChannelMessage` por evento procesable; vacía si solo hay estados u
        otros eventos descartados.

    Raises:
        ValidationError: Si un evento con `message` carece de `mid` o tiene un
            timestamp inválido.

    Example:
        >>> mensajes = parse(
        ...     {"entry": [{"messaging": [{
        ...         "sender": {"id": "PSID"},
        ...         "recipient": {"id": "PAGE_1"},
        ...         "timestamp": 1712345678000,
        ...         "message": {"mid": "mid.1", "text": "hola"},
        ...     }]}]}
        ... )
        >>> (mensajes[0].text, mensajes[0].emitter_id, mensajes[0].message_id)
        ('hola', 'PAGE_1', 'mid.1')
    """
    return parse_messaging(payload, channel=_CANAL)
