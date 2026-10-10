"""Contract tests: los parsers de los 3 canales traducen los payloads de Meta (Fase 3).

Réplica de los formatos reales que analiza el legacy (`whatsapp_adapter`,
`facebook_adapter`, `instagram_adapter`): mensajes, media, estados descartados,
ecos, respuestas a historias y errores de payload malformado.
"""

from datetime import UTC, datetime
from typing import Literal

import pytest

from shared.errors import ValidationError
from slices.conversation_gateway.infrastructure.channels import parse_event
from slices.conversation_gateway.infrastructure.channels.instagram.parser import (
    parse as parse_instagram,
)
from slices.conversation_gateway.infrastructure.channels.messenger.parser import (
    parse as parse_messenger,
)
from slices.conversation_gateway.infrastructure.channels.whatsapp.parser import (
    parse as parse_whatsapp,
)

pytestmark = pytest.mark.contract

_EPOCH_S = "1712345678"
_EPOCH_MS = 1_712_345_678_000
_DISPLAY = "5730012345678"


def _wa_value(
    *,
    mensajes: list[dict[str, object]] | None,
    metadata: dict[str, object] | Literal["default"] | None = "default",
    contacts: list[dict[str, object]] | None = None,
    statuses: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Objeto `value` de WhatsApp con las claves pedidas.

    Args:
        mensajes: Lista `messages` (`None` = sin clave `messages`).
        metadata: Objeto `metadata` (`"default"` = el habitual; `None` = ausente).
        contacts: Lista `contacts` opcional.
        statuses: Lista `statuses` opcional (estados de lectura).

    Returns:
        El dict `value`.
    """
    value: dict[str, object] = {}
    if metadata == "default":
        value["metadata"] = {
            "phone_number_id": "1000",
            "display_phone_number": _DISPLAY,
        }
    elif metadata is not None:
        value["metadata"] = metadata
    if contacts is not None:
        value["contacts"] = contacts
    if mensajes is not None:
        value["messages"] = mensajes
    if statuses is not None:
        value["statuses"] = statuses
    return value


def _wa(
    *,
    mensajes: list[dict[str, object]] | None,
    metadata: dict[str, object] | Literal["default"] | None = "default",
    contacts: list[dict[str, object]] | None = None,
    statuses: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Envelope mínimo de WhatsApp con un solo `change`.

    Args:
        mensajes: Lista `messages` (`None` = sin clave `messages`).
        metadata: Objeto `metadata` (`"default"` = el habitual; `None` = ausente).
        contacts: Lista `contacts` opcional.
        statuses: Lista `statuses` opcional (estados de lectura).

    Returns:
        El payload completo del webhook.
    """
    value = _wa_value(mensajes=mensajes, metadata=metadata, contacts=contacts, statuses=statuses)
    return {"entry": [{"changes": [{"field": "messages", "value": value}]}]}


def _msg_wa(**campos: object) -> dict[str, object]:
    """Mensaje base de WhatsApp (`from`, `id`, `timestamp`) sobrescribible por kwargs."""
    base: dict[str, object] = {
        "from": "573001112222",
        "id": "wamid.ABC",
        "timestamp": _EPOCH_S,
        "type": "text",
    }
    base.update(campos)
    return base


def _evento_fb(**campos: object) -> dict[str, object]:
    """Evento base de Messenger/Instagram (`sender`, `recipient`, `timestamp`)."""
    base: dict[str, object] = {
        "sender": {"id": "PSID_1"},
        "recipient": {"id": "PAGE_1"},
        "timestamp": _EPOCH_MS,
        "message": {"mid": "mid.1", "text": "hola"},
    }
    base.update(campos)
    return base


def _fb(eventos: list[dict[str, object]]) -> dict[str, object]:
    """Envelope mínimo de Messenger/Instagram con un solo `entry`."""
    return {"entry": [{"messaging": eventos}]}


# --- WhatsApp ---------------------------------------------------------------------------


def test_whatsapp_texto_con_nombre_de_perfil() -> None:
    """Rutas completas: emitter=phone_number_id, wamid, epoch s→UTC, nombre del perfil."""
    payload = _wa(
        mensajes=[_msg_wa(text={"body": "hola"})],
        contacts=[{"wa_id": "573001112222", "profile": {"name": "Ana"}}],
    )
    (mensaje,) = parse_whatsapp(payload)
    assert mensaje.channel == "whatsapp"
    assert mensaje.emitter_id == "1000"
    assert mensaje.customer_id == "573001112222"
    assert mensaje.message_id == "wamid.ABC"
    assert mensaje.timestamp == datetime.fromtimestamp(int(_EPOCH_S), tz=UTC)
    assert mensaje.message_type == "text"
    assert mensaje.text == "hola"
    assert mensaje.sender_name == "Ana"


def test_whatsapp_imagen_con_caption_atribuye_el_media() -> None:
    """La imagen aporta `image.id` y caption; la clase de media queda en `media_type`."""
    payload = _wa(mensajes=[_msg_wa(type="image", image={"id": "MEDIA_1", "caption": "mira"})])
    (mensaje,) = parse_whatsapp(payload)
    assert mensaje.message_type == "image"
    assert mensaje.text == "mira"
    assert mensaje.media_id == "MEDIA_1"
    assert mensaje.media_type == "image"


def test_whatsapp_audio_sin_caption_solo_atributos() -> None:
    """Decisión de alcance: la media va sin texto (el placeholder lo pone el consumer)."""
    payload = _wa(mensajes=[_msg_wa(type="audio", audio={"id": "AUD_1"})])
    (mensaje,) = parse_whatsapp(payload)
    assert mensaje.message_type == "audio"
    assert mensaje.text is None
    assert (mensaje.media_id, mensaje.media_type) == ("AUD_1", "audio")


def test_whatsapp_documento_usa_filename_como_texto() -> None:
    """Sin caption, el `filename` es lo único legible del documento (formato legacy)."""
    payload = _wa(
        mensajes=[_msg_wa(type="document", document={"id": "DOC_1", "filename": "factura.pdf"})]
    )
    (mensaje,) = parse_whatsapp(payload)
    assert mensaje.message_type == "document"
    assert mensaje.text == "factura.pdf"


def test_whatsapp_ubicacion_se_reconstruye_como_texto() -> None:
    """Location no trae id: el texto replica el formato `Location: lat, lng` legacy."""
    payload = _wa(
        mensajes=[_msg_wa(type="location", location={"latitude": 4.7, "longitude": -74.1})]
    )
    (mensaje,) = parse_whatsapp(payload)
    assert mensaje.message_type == "location"
    assert mensaje.text == "Location: 4.7, -74.1"


def test_whatsapp_sticker_solo_atributos() -> None:
    """Sticker: `sticker.id` como media, sin texto."""
    payload = _wa(mensajes=[_msg_wa(type="sticker", sticker={"id": "STK_1"})])
    (mensaje,) = parse_whatsapp(payload)
    assert mensaje.message_type == "sticker"
    assert (mensaje.text, mensaje.media_id) == (None, "STK_1")


def test_whatsapp_estados_de_lectura_se_descartan() -> None:
    """`value.statuses` (entregado/leído) no genera mensaje: 200 sin reprocesar."""
    assert parse_whatsapp(_wa(mensajes=None, statuses=[{"id": "wamid.1", "status": "read"}])) == []


def test_whatsapp_eco_propio_se_descarta() -> None:
    """`from == display_phone_number` es nuestro propio envío: no hay turno."""
    payload = _wa(mensajes=[_msg_wa(**{"from": _DISPLAY})])
    assert parse_whatsapp(payload) == []


def test_whatsapp_tipo_no_soportado_se_descarta() -> None:
    """reaction/interactive quedan fuera por ahora (TODO(decision) en el parser)."""
    assert parse_whatsapp(_wa(mensajes=[_msg_wa(type="reaction", reaction={"emoji": "+"})])) == []


def test_whatsapp_varios_mensajes_en_un_cambio() -> None:
    """Meta puede agrupar: todos los mensajes del `value` salen normalizados."""
    payload = _wa(
        mensajes=[
            _msg_wa(id="wamid.1"),
            _msg_wa(id="wamid.2", text={"body": "segundo"}),
        ]
    )
    mensajes = parse_whatsapp(payload)
    assert [m.message_id for m in mensajes] == ["wamid.1", "wamid.2"]
    assert mensajes[1].text == "segundo"


def test_whatsapp_varios_changes_y_entries() -> None:
    """Se recorren todos los `entry[].changes[]` (como el V2 del legacy), no solo el primero."""
    payload = {
        "entry": [
            {"changes": [{"value": _wa_value(mensajes=[_msg_wa(id="wamid.1")])}]},
            {"changes": [{"value": _wa_value(mensajes=[_msg_wa(id="wamid.2")])}]},
        ]
    }
    assert [m.message_id for m in parse_whatsapp(payload)] == ["wamid.1", "wamid.2"]


def test_whatsapp_sin_metadata_es_error() -> None:
    """Sin `phone_number_id` no se puede resolver tenant: payload malformado, se alza."""
    with pytest.raises(ValidationError):
        parse_whatsapp(_wa(mensajes=[_msg_wa()], metadata=None))


def test_whatsapp_sin_remitente_es_error() -> None:
    """Sin `from` ni contacts no hay cliente posible (legacy: ValueError)."""
    payload = _wa(mensajes=[{"id": "wamid.1", "timestamp": _EPOCH_S, "type": "text"}])
    with pytest.raises(ValidationError):
        parse_whatsapp(payload)


def test_whatsapp_remitente_falla_hacia_contacts() -> None:
    """Sin `from`, el legacy usa `contacts[0].wa_id` como remitente."""
    payload = _wa(
        mensajes=[
            {"id": "wamid.1", "timestamp": _EPOCH_S, "type": "text", "text": {"body": "hola"}}
        ],
        contacts=[{"wa_id": "57300999", "profile": {"name": "Beto"}}],
    )
    (mensaje,) = parse_whatsapp(payload)
    assert mensaje.customer_id == "57300999"
    assert mensaje.sender_name == "Beto"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("timestamp", "ayer"),
        ("timestamp", None),
        ("id", None),
    ],
)
def test_whatsapp_campos_invalidos_son_error(*, campo: str, valor: object) -> None:
    """`id` y `timestamp` son obligatorios y numéricos: el payload malformado se alza."""
    con_campo = _msg_wa()
    con_campo[campo] = valor
    with pytest.raises(ValidationError):
        parse_whatsapp(_wa(mensajes=[con_campo]))


# --- Messenger ---------------------------------------------------------------------------


def test_messenger_texto_usa_recipient_como_emisor() -> None:
    """Clave del mapeo IG/FB: `recipient.id` (página) es el emisor; `sender.id` el cliente."""
    (mensaje,) = parse_messenger(_fb([_evento_fb()]))
    assert mensaje.channel == "messenger"
    assert mensaje.emitter_id == "PAGE_1"
    assert mensaje.customer_id == "PSID_1"
    assert mensaje.message_id == "mid.1"
    assert mensaje.timestamp == datetime.fromtimestamp(_EPOCH_MS // 1000, tz=UTC)
    assert (mensaje.message_type, mensaje.text) == ("text", "hola")


def test_messenger_adjunto_imagen_atribuye_url() -> None:
    """Graph API da `payload.url` (no id): `media_url` y la clase en `media_type`."""
    evento = _evento_fb(
        message={
            "mid": "mid.2",
            "attachments": [{"type": "image", "payload": {"url": "https://f.example/a.jpg"}}],
        }
    )
    (mensaje,) = parse_messenger(_fb([evento]))
    assert mensaje.message_type == "image"
    assert mensaje.media_url == "https://f.example/a.jpg"
    assert mensaje.media_type == "image"
    assert mensaje.text is None


def test_messenger_adjunto_file_es_document() -> None:
    """Mapeo legacy: `file` → `document`."""
    evento = _evento_fb(
        message={
            "mid": "mid.3",
            "attachments": [{"type": "file", "payload": {"url": "https://f.example/x.pdf"}}],
        }
    )
    (mensaje,) = parse_messenger(_fb([evento]))
    assert mensaje.message_type == "document"
    assert mensaje.media_type == "document"


def test_messenger_ubicacion_atribuye_lat_long() -> None:
    """Adjunto `location` con `coordinates.lat/long` (soporte propio de Facebook)."""
    evento = _evento_fb(
        message={
            "mid": "mid.4",
            "attachments": [
                {
                    "type": "location",
                    "payload": {"coordinates": {"lat": 4.7, "long": -74.1}},
                }
            ],
        }
    )
    (mensaje,) = parse_messenger(_fb([evento]))
    assert mensaje.message_type == "location"
    assert mensaje.text == "Location: 4.7, -74.1"


def test_messenger_delivery_y_postback_se_descartan() -> None:
    """`delivery`/`read`/`postback` vienen sin `message`: 200 sin reprocesar (legacy)."""
    assert parse_messenger(_fb([{"sender": {"id": "PSID_1"}, "delivery": {"mids": []}}])) == []
    assert parse_messenger(_fb([{"sender": {"id": "PSID_1"}, "postback": {"title": "x"}}])) == []


def test_messenger_echo_se_descarta() -> None:
    """Los ecos de nuestras propias respuestas jamás vuelven al pipeline."""
    evento = _evento_fb(message={"mid": "mid.5", "text": "eco", "is_echo": True})
    assert parse_messenger(_fb([evento])) == []


def test_messenger_evento_sin_sender_se_descarta() -> None:
    """Evento con `message` pero sin identidad: el legacy lo descarta con `continue`."""
    evento: dict[str, object] = {
        "timestamp": _EPOCH_MS,
        "message": {"mid": "mid.6", "text": "hola"},
    }
    assert parse_messenger(_fb([evento])) == []


def test_messenger_evento_sin_mensaje_ni_contenido_se_descarta() -> None:
    """`message` sin texto ni adjunto no genera turno (nada que procesar)."""
    evento = _evento_fb(message={"mid": "mid.7"})
    assert parse_messenger(_fb([evento])) == []


def test_messenger_evento_sin_timestamp_es_error() -> None:
    """Un `message` válido exige timestamp numérico: payload malformado, se alza."""
    evento = _evento_fb(timestamp=None)
    with pytest.raises(ValidationError):
        parse_messenger(_fb([evento]))


# --- Instagram ---------------------------------------------------------------------------


def test_instagram_comparte_envelope_y_emisor_con_messenger() -> None:
    """Mismo envelope que Facebook (`object: instagram`); el emisor sigue siendo la página."""
    payload = {"object": "instagram", **_fb([_evento_fb()])}
    (mensaje,) = parse_instagram(payload)
    assert mensaje.channel == "instagram"
    assert mensaje.emitter_id == "PAGE_1"
    assert mensaje.text == "hola"


def test_instagram_respuesta_a_historia_se_normaliza() -> None:
    """`event.story` sin `message` → `story_<id>` con prefijo `[Story Reply]` (legacy)."""
    evento: dict[str, object] = {
        "sender": {"id": "IG_USER"},
        "recipient": {"id": "PAGE_1"},
        "timestamp": _EPOCH_MS,
        "story": {"id": "9", "reply": "checo"},
    }
    (mensaje,) = parse_instagram(_fb([evento]))
    assert mensaje.message_id == "story_9"
    assert mensaje.message_type == "text"
    assert mensaje.text == "[Story Reply] checo"


def test_instagram_historia_sin_respuesta_se_descarta() -> None:
    """Una historia sin `reply` no aporta contenido: se ignora."""
    evento: dict[str, object] = {
        "sender": {"id": "IG_USER"},
        "recipient": {"id": "PAGE_1"},
        "timestamp": _EPOCH_MS,
        "story": {"id": "9"},
    }
    assert parse_instagram(_fb([evento])) == []


# --- registro por canal --------------------------------------------------------------------


def test_parse_event_despacha_al_parser_del_canal() -> None:
    """El registro de `channels/__init__` enlaza cada canal con su parser (ADR 0009)."""
    wa = _wa(mensajes=[_msg_wa()])
    fb = _fb([_evento_fb()])
    assert parse_event(wa, channel="whatsapp")[0].channel == "whatsapp"
    assert parse_event(fb, channel="messenger")[0].channel == "messenger"
    assert parse_event(fb, channel="instagram")[0].channel == "instagram"
