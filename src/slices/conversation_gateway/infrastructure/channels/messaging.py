"""Envelope `entry[].messaging[]` de Graph API: común a Messenger e Instagram.

Replica `facebook_adapter.normalize_message` e `instagram_adapter.normalize_message`
del legacy: recorre todos los eventos, descarta ecos (`is_echo`), estados
(`delivery`/`read`/`postback`, que vienen sin `message`) y clasifica el tipo por
`attachments[0]` — igual que el legacy, que solo mira el primer adjunto.
"""

from collections.abc import Mapping

from shared.contracts.types import Channel
from shared.ports import ChannelMessage, MessageType
from slices.conversation_gateway.infrastructure.channels.payload import (
    cadena,
    cadena_requerida,
    epoch,
    lista,
    objeto,
)

# Mapeo del `type` del adjunto al `MessageType` interno (legacy: `file` → document).
_A_TIPO_ADJUNTO: dict[str, MessageType] = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "file": "document",
    "location": "location",
}


def parse_messaging(payload: Mapping[str, object], *, channel: Channel) -> list[ChannelMessage]:
    """Normaliza todos los eventos con `message` del envelope Messenger/Instagram.

    Args:
        payload: JSON del webhook (`entry[].messaging[]`).
        channel: Canal concreto (`messenger` o `instagram`).

    Returns:
        Un `ChannelMessage` por evento procesable; vacía si solo hay estados u
        otros eventos descartados.

    Raises:
        ValidationError: Si un evento con `message` carece de `mid` o tiene un
            timestamp inválido (payload malformado que Meta no envía).
    """
    mensajes: list[ChannelMessage] = []
    for entrada in lista(payload.get("entry")):
        objeto_entrada = objeto(entrada)
        if objeto_entrada is None:
            continue
        for evento_bruto in lista(objeto_entrada.get("messaging")):
            evento = objeto(evento_bruto)
            if evento is None:
                continue
            resultado = _evento_a_mensaje(evento, channel=channel)
            if resultado is not None:
                mensajes.append(resultado)
    return mensajes


def parse_story_replies(payload: Mapping[str, object], *, channel: Channel) -> list[ChannelMessage]:
    """Normaliza las respuestas a historias de Instagram (`event.story`, sin `message`).

    Réplica de `_normalize_story_reply` del legacy: `message_id = story_<id>` y el
    texto `[Story Reply] <respuesta>`.

    Args:
        payload: JSON del webhook.
        channel: Canal del envelope (siempre `instagram`; el argumento hace explícita
            la restricción).

    Returns:
        Un `ChannelMessage` por respuesta a historia; vacía si no hay.

    Raises:
        ValidationError: Si la historia carece de `id` o el timestamp es inválido.
    """
    mensajes: list[ChannelMessage] = []
    for entrada in lista(payload.get("entry")):
        objeto_entrada = objeto(entrada)
        if objeto_entrada is None:
            continue
        for evento_bruto in lista(objeto_entrada.get("messaging")):
            evento = objeto(evento_bruto)
            if evento is None or objeto(evento.get("message")) is not None:
                continue
            historia = objeto(evento.get("story"))
            if historia is None:
                continue
            identidad = _identidad_evento(evento)
            if identidad is None:
                continue
            emisor, remitente = identidad
            historia_id = cadena_requerida(historia.get("id"), campo="story.id")
            respuesta = cadena(historia.get("reply"))
            if respuesta is None:
                continue
            mensajes.append(
                ChannelMessage(
                    channel=channel,
                    emitter_id=emisor,
                    customer_id=remitente,
                    message_id=f"story_{historia_id}",
                    timestamp=epoch(evento.get("timestamp"), campo="timestamp", milisegundos=True),
                    message_type="text",
                    text=f"[Story Reply] {respuesta}",
                )
            )
    return mensajes


def _identidad_evento(evento: Mapping[str, object]) -> tuple[str, str] | None:
    """Extrae `(emisor, remitente)` del evento; `None` si el evento no los trae.

    El emisor Meta de IG/FB es `recipient.id` (id de página): es la clave del mapeo
    `IG_CONFIG#`/`FB_CONFIG#` del legacy; el remitente es `sender.id` (PSID).

    Args:
        evento: Un elemento de `messaging[]`.

    Returns:
        Tupla `(emitter_id, customer_id)` o `None` si falta alguno (el legacy
        descarta el evento con `continue`).
    """
    remitente = objeto(evento.get("sender"))
    destinatario = objeto(evento.get("recipient"))
    if remitente is None or destinatario is None:
        return None
    customer_id = cadena(remitente.get("id"))
    emisor = cadena(destinatario.get("id"))
    if not customer_id or not emisor:
        return None
    return (emisor, customer_id)


def _evento_a_mensaje(evento: Mapping[str, object], *, channel: Channel) -> ChannelMessage | None:
    """Traduce un evento de `messaging[]` con `message`; `None` si se descarta.

    Args:
        evento: Un elemento de `messaging[]`.
        channel: Canal concreto del envelope.

    Returns:
        El mensaje normalizado o `None` (estado, eco, evento sin contenido).

    Raises:
        ValidationError: Si falta `mid` o el timestamp es inválido.
    """
    mensaje = objeto(evento.get("message"))
    if mensaje is None:
        # delivery/read/postback/reaction/account_update: sin `message`, sin turno.
        return None
    if mensaje.get("is_echo"):
        # Respuesta propia del bot: jamás vuelve al pipeline (legacy V2).
        return None
    identidad = _identidad_evento(evento)
    if identidad is None:
        return None
    emisor, remitente = identidad
    texto, tipo, media_url, media_id, media_type = _contenido(mensaje)
    if texto is None and media_url is None:
        # Sin texto ni adjunto consultable no hay nada que procesar.
        return None
    return ChannelMessage(
        channel=channel,
        emitter_id=emisor,
        customer_id=remitente,
        message_id=cadena_requerida(mensaje.get("mid"), campo="mid"),
        timestamp=epoch(evento.get("timestamp"), campo="timestamp", milisegundos=True),
        message_type=tipo,
        text=texto,
        media_id=media_id,
        media_type=media_type,
        media_url=media_url,
    )


def _contenido(
    mensaje: Mapping[str, object],
) -> tuple[str | None, MessageType, str | None, str | None, str | None]:
    """Extrae texto, tipo y atributos de media del objeto `message`.

    Args:
        mensaje: El objeto `message` del evento.

    Returns:
        Tupla `(text, message_type, media_url, media_id, media_type)`; el texto de
        una ubicación se reconstruye como `Location: lat, long` (formato legacy) y
        `media_id` queda en `None` porque Graph API solo da la URL del adjunto.
    """
    texto = cadena(mensaje.get("text"))
    tipo: MessageType = "text"
    media_url: str | None = None
    media_id: str | None = None
    media_type: str | None = None
    adjuntos = lista(mensaje.get("attachments"))
    if adjuntos:
        primero = objeto(adjuntos[0])
        if primero is not None:
            clase = cadena(primero.get("type")) or ""
            tipo = _A_TIPO_ADJUNTO.get(clase, "text")
            bloque = objeto(primero.get("payload"))
            if bloque is not None:
                media_url = cadena(bloque.get("url"))
                if clase == "location":
                    texto = _ubicacion(bloque)
                elif tipo != "text":
                    media_type = tipo
    return (texto, tipo, media_url, media_id, media_type)


def _ubicacion(bloque: Mapping[str, object]) -> str | None:
    """Reconstruye el texto de una ubicación adjunta (`coordinates.lat/long`).

    Args:
        bloque: `payload` del adjunto de tipo `location`.

    Returns:
        `Location: lat, long` o `None` si las coordenadas no vienen.
    """
    coordenadas = objeto(bloque.get("coordinates"))
    if coordenadas is None:
        return None
    lat = coordenadas.get("lat")
    largo = coordenadas.get("long")
    if lat is None or largo is None:
        return None
    return f"Location: {lat}, {largo}"
