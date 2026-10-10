"""Detección del canal a partir del envelope del webhook (regla pura, común a los 3).

Meta entrega los tres canales en el mismo endpoint: el canal se distingue por el
campo `object` del JSON. La interpretación del **mensaje** de cada canal ya es del
adaptador correspondiente (`ChannelPort.normalize_inbound`, ADR 0009).

El filtro de «eventos a ignorar» (estados de lectura, reacciones) vive en los
adaptadores: aquí solo se identifica el canal.
"""

from collections.abc import Mapping

from shared.contracts.types import Channel

_OBJETOS_META: dict[str, Channel] = {
    "whatsapp_business_account": "whatsapp",
    "instagram": "instagram",
    "page": "messenger",
}
# TODO(verify): valores exactos del campo `object` según Graph API v24.0 (documentación
# de Meta); si Meta envía un envelope sin `object`, se ignora (None) y no se procesa.


def detect_channel(payload: Mapping[str, object]) -> Channel | None:
    """Identifica el canal al que pertenece el payload del webhook.

    Args:
        payload: JSON ya parseado del POST (envelope completo de Meta).

    Returns:
        El canal Meta (`whatsapp`/`instagram`/`messenger`) o `None` si el envelope
        no corresponde a ninguno de los tres: el handler responde 200 sin procesar,
        igual que con los estados de lectura.

    Example:
        >>> detect_channel({"object": "whatsapp_business_account"})
        'whatsapp'
        >>> detect_channel({"object": "unknown_platform"}) is None
        True
    """
    objeto = payload.get("object")
    if isinstance(objeto, str):
        return _OBJETOS_META.get(objeto)
    return None
