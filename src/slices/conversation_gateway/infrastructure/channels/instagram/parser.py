"""Parser del webhook de Instagram → lista de `ChannelMessage` (Fase 3).

Envelope de Graph API (`entry[].messaging[]`) compartido con Messenger, más las
respuestas a historias (`event.story`, sin `message`), que el legacy trata en
`instagram_adapter._normalize_story_reply`. Los adjuntos `file` se traducen a
`document`, igual que en el legacy.
"""

from collections.abc import Mapping

from shared.contracts.types import Channel
from shared.ports import ChannelMessage
from slices.conversation_gateway.infrastructure.channels.messaging import (
    parse_messaging,
    parse_story_replies,
)

_CANAL: Channel = "instagram"


def parse(payload: Mapping[str, object]) -> list[ChannelMessage]:
    """Normaliza todos los mensajes y respuestas a historias del envelope de Instagram.

    Args:
        payload: JSON del webhook (`entry[].messaging[]` y `entry[].messaging[].story`).

    Returns:
        Un `ChannelMessage` por evento procesable; vacía si solo hay estados u
        otros eventos descartados.

    Raises:
        ValidationError: Si un evento con `message` carece de `mid`, o una historia
            carece de `id`, o algún timestamp es inválido.

    Example:
        >>> mensajes = parse(
        ...     {"entry": [{"messaging": [{
        ...         "sender": {"id": "IG_USER"},
        ...         "recipient": {"id": "PAGE_1"},
        ...         "timestamp": 1712345678000,
        ...         "message": {"mid": "mid.1", "text": "hola"},
        ...     }]}]}
        ... )
        >>> (mensajes[0].text, mensajes[0].emitter_id, mensajes[0].channel)
        ('hola', 'PAGE_1', 'instagram')
    """
    mensajes = parse_messaging(payload, channel=_CANAL)
    mensajes.extend(parse_story_replies(payload, channel=_CANAL))
    return mensajes
