"""Parser del webhook de WhatsApp Cloud API → lista de `ChannelMessage` (Fase 3).

Replica las rutas del legacy (`whatsapp_adapter.normalize_message` y
`whatsapp_orchestrator.process_meta_message`): recorre todos los
`entry[].changes[].value`, procesa `value.messages[]`, descarta `value.statuses`
(estados de lectura) y el eco propio, y clasifica el tipo con el campo `type` del
mensaje. El `mime_type` no viene en el payload: Meta lo aporta al consultar la
Graph API durante la descarga (`media_handling`).
"""

from collections.abc import Mapping

from shared.contracts.types import Channel
from shared.errors import ValidationError
from shared.ports import ChannelMessage, MessageType
from slices.conversation_gateway.infrastructure.channels.payload import (
    cadena,
    cadena_requerida,
    epoch,
    lista,
    objeto,
)

_CANAL: Channel = "whatsapp"

# Única fuente de verdad del canal: claves = tipos del payload soportados → tipo
# interno. reaction/interactive/button quedan fuera hoy:
# TODO(decision) replicar el legacy (REACTION con emoji e interactive→TEXT) cuando
# existan flujos con botones en el agente.
_A_TIPO: dict[str, MessageType] = {
    "text": "text",
    "image": "image",
    "audio": "audio",
    "video": "video",
    "document": "document",
    "location": "location",
    "sticker": "sticker",
}
_TIPOS_SOPORTADOS = frozenset(_A_TIPO)


def parse(payload: Mapping[str, object]) -> list[ChannelMessage]:
    """Normaliza todos los mensajes del envelope de WhatsApp.

    Args:
        payload: JSON del webhook (`entry[].changes[].value`).

    Returns:
        Un `ChannelMessage` por mensaje procesable; vacía si el `value` solo trae
        `statuses` u otros tipos descartados (eco, reaction…).

    Raises:
        ValidationError: Si hay mensajes sin `metadata.phone_number_id`, sin
            remitente o con timestamp inválido (payload malformado).

    Example:
        >>> mensaje = parse(
        ...     {"entry": [{"changes": [{"value": {
        ...         "metadata": {"phone_number_id": "1000"},
        ...         "messages": [{"from": "57300", "id": "wamid.1",
        ...                        "timestamp": "1712345678", "type": "text",
        ...                        "text": {"body": "hola"}}],
        ...     }}]}]}
        ... )
        >>> (mensaje[0].text, mensaje[0].emitter_id, mensaje[0].message_type)
        ('hola', '1000', 'text')
    """
    mensajes: list[ChannelMessage] = []
    for entrada in lista(payload.get("entry")):
        objeto_entrada = objeto(entrada)
        if objeto_entrada is None:
            continue
        for cambio in lista(objeto_entrada.get("changes")):
            objeto_cambio = objeto(cambio)
            if objeto_cambio is None:
                continue
            valor = objeto(objeto_cambio.get("value"))
            if valor is None:
                continue
            mensajes.extend(_valor_a_mensajes(valor))
    return mensajes


def _valor_a_mensajes(valor: Mapping[str, object]) -> list[ChannelMessage]:
    """Traduce un `changes[].value` completo (puede traer varios mensajes).

    Args:
        valor: Objeto `value` del cambio.

    Returns:
        Los mensajes procesables de ese `value`; vacía si no trae `messages`
        (estados de lectura u otros updates: se ignoran como el legacy).

    Raises:
        ValidationError: Si faltan `metadata`, el remitente o un timestamp.
    """
    brutos = lista(valor.get("messages"))
    if not brutos:
        return []
    metadata = objeto(valor.get("metadata"))
    if metadata is None:
        raise ValidationError("webhook de whatsapp sin metadata (phone_number_id)")
    emisor = cadena_requerida(metadata.get("phone_number_id"), campo="phone_number_id")
    display = cadena(metadata.get("display_phone_number"))
    primer_remitente, nombres = _contactos(valor)
    mensajes: list[ChannelMessage] = []
    for bruto in brutos:
        mensaje = objeto(bruto)
        if mensaje is None:
            raise ValidationError("mensaje de whatsapp que no es un objeto JSON")
        resultado = _mensaje_a_channel_message(
            mensaje,
            emisor=emisor,
            display=display,
            primer_remitente=primer_remitente,
            nombres=nombres,
        )
        if resultado is not None:
            mensajes.append(resultado)
    return mensajes


def _contactos(valor: Mapping[str, object]) -> tuple[str | None, dict[str, str]]:
    """Indexa `value.contacts[]` (fallback de remitente y nombre del perfil).

    Args:
        valor: Objeto `value` del cambio.

    Returns:
        Tupla `(primer_wa_id, nombres_por_wa_id)`; el primer `wa_id` es el fallback
        de `from` que usa el legacy y los nombres salen de `profile.name`.
    """
    primer_remitente: str | None = None
    nombres: dict[str, str] = {}
    for contacto_bruto in lista(valor.get("contacts")):
        contacto = objeto(contacto_bruto)
        if contacto is None:
            continue
        wa_id = cadena(contacto.get("wa_id"))
        if wa_id and primer_remitente is None:
            primer_remitente = wa_id
        perfil = objeto(contacto.get("profile"))
        nombre = cadena(perfil.get("name")) if perfil is not None else None
        if wa_id and nombre:
            nombres[wa_id] = nombre
    return (primer_remitente, nombres)


def _mensaje_a_channel_message(
    mensaje: Mapping[str, object],
    *,
    emisor: str,
    display: str | None,
    primer_remitente: str | None,
    nombres: dict[str, str],
) -> ChannelMessage | None:
    """Traduce un mensaje de WhatsApp; `None` si se descarta (eco o tipo no soportado).

    Args:
        mensaje: Un elemento de `value.messages[]`.
        emisor: `phone_number_id` del value (clave del mapeo al tenant).
        display: `display_phone_number` para filtrar el eco propio.
        primer_remitente: Fallback de remitente (`contacts[0].wa_id`).
        nombres: Nombre del perfil por `wa_id`.

    Returns:
        El mensaje normalizado, o `None` si es eco o de un tipo descartado.

    Raises:
        ValidationError: Si el tipo es soportado pero faltan `id`, remitente o
            timestamp.
    """
    tipo = cadena(mensaje.get("type")) or ""
    if tipo not in _TIPOS_SOPORTADOS:
        return None
    remitente = cadena(mensaje.get("from")) or primer_remitente
    if not remitente:
        raise ValidationError("mensaje de whatsapp sin remitente (from ni contacts)")
    if display and remitente == display:
        # Nuestro propio envío reflejado en el webhook: no genera turno (legacy V2).
        return None
    texto, media_id, media_type = _contenido(tipo, mensaje)
    return ChannelMessage(
        channel=_CANAL,
        emitter_id=emisor,
        customer_id=remitente,
        message_id=cadena_requerida(mensaje.get("id"), campo="id"),
        timestamp=epoch(mensaje.get("timestamp"), campo="timestamp"),
        message_type=_A_TIPO[tipo],
        text=texto,
        media_id=media_id,
        media_type=media_type,
        sender_name=nombres.get(remitente),
    )


def _contenido(
    tipo: str, mensaje: Mapping[str, object]
) -> tuple[str | None, str | None, str | None]:
    """Extrae texto y atributos de media según el tipo del mensaje.

    Args:
        tipo: El campo `type` del payload (ya validado como soportado).
        mensaje: El mensaje completo.

    Returns:
        Tupla `(text, media_id, media_type)`. La ubicación se reconstruye como
        `Location: lat, lng` (formato legacy); `media_type` es la clase del medio
        (`image`/`audio`/…): el MIME real lo aporta la Graph API al descargarlo.
    """
    texto: str | None = None
    media_id: str | None = None
    media_type: str | None = None
    if tipo == "text":
        bloque = objeto(mensaje.get("text"))
        texto = cadena(bloque.get("body")) if bloque is not None else None
    elif tipo in {"image", "audio", "video", "document"}:
        bloque = objeto(mensaje.get(tipo))
        if bloque is not None:
            media_id = cadena(bloque.get("id"))
            media_type = tipo
            if tipo == "document":
                texto = cadena(bloque.get("caption")) or cadena(bloque.get("filename"))
            elif tipo in {"image", "video"}:
                texto = cadena(bloque.get("caption"))
    elif tipo == "location":
        bloque = objeto(mensaje.get("location"))
        if bloque is not None and bloque.get("latitude") is not None:
            texto = f"Location: {bloque.get('latitude')}, {bloque.get('longitude')}"
    elif tipo == "sticker":
        bloque = objeto(mensaje.get("sticker"))
        if bloque is not None:
            media_id = cadena(bloque.get("id"))
            media_type = "sticker"
    return (texto, media_id, media_type)
