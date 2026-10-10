"""Adapter de canal Meta sobre los parsers de los 3 canales (recepción, Fase 4).

Implementa la vista de entrada (`NormalizerPort`) que consume el `WebhookReceiver`:
delega en el registro `parse_event` de la Fase 3, que selecciona el parser según el
canal ya detectado en el envelope.
"""

from collections.abc import Mapping

from shared.contracts.types import Channel
from shared.ports import ChannelMessage
from slices.conversation_gateway.infrastructure.channels import parse_event


class MetaChannel:
    """Normaliza el payload de WhatsApp, Instagram o Messenger a `ChannelMessage`.

    `send` y `verify_credentials` del `ChannelPort` completo (ADR 0009) llegan con
    las credenciales (Fase 5) y el envío de respuestas (Fase 6): hoy la aplicación
    del webhook solo necesita `normalize_inbound`.

    Example:
        >>> from slices.conversation_gateway.infrastructure.channels.meta import MetaChannel
        >>> canal = MetaChannel()
        >>> canal.normalize_inbound({"entry": []}, channel="whatsapp")
        []
    """

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
