"""Tests del flujo de la Fase 4: normalizar → resolver tenant → deduplicar → encolar.

El webhook no procesa: solo acusa, y para eso tiene que haber pasado la firma, el
mapeo canal→tenant y la deduplicación. Estos tests fijan esas garantías sin crear
clientes AWS (dobles en memoria) y sin tocar la cola.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from shared.contracts.types import Channel
from shared.errors import ToolError
from shared.ports import ChannelMessage
from slices.conversation_gateway.application.webhook import WebhookReceiver
from slices.conversation_gateway.domain.errors import DuplicateMessageError
from slices.conversation_gateway.domain.ports import NormalizerPort
from slices.conversation_gateway.infrastructure.channels.meta import MetaChannel
from slices.conversation_gateway.infrastructure.in_memory import (
    InMemoryChannel,
    InMemoryDeduplication,
    InMemoryEventBus,
    InMemoryTenantResolver,
)

_TOKEN = "token-de-verificacion"
_SECRETO = "app-secreta-del-test"
_TENANT = "Sede_Elite_01"
_MAPA: dict[tuple[Channel, str], str] = {("whatsapp", "1000"): _TENANT}


def _firma(cuerpo: bytes) -> str:
    """Firma de prueba con el mismo algoritmo que Meta (HMAC-SHA256)."""
    return "sha256=" + hmac.new(_SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()


def _payload_wa(*, mensajes: list[dict[str, object]] | None = None) -> bytes:
    """Envelope de WhatsApp con uno o dos mensajes sintéticos (wa_id `573001112222`).

    Args:
        mensajes: Mensajes a incluir; por defecto un `wamid.1` de texto «hola».

    Returns:
        El cuerpo crudo del webhook, listo para firmar.
    """
    if mensajes is None:
        mensajes = [
            {
                "from": "573001112222",
                "id": "wamid.1",
                "timestamp": "1712345678",
                "type": "text",
                "text": {"body": "hola"},
            }
        ]
    envelope = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {
                                "phone_number_id": "1000",
                                "display_phone_number": "5730012345678",
                            },
                            "messages": mensajes,
                        }
                    }
                ]
            }
        ],
    }
    return json.dumps(envelope).encode("utf-8")


def _receptor(
    *,
    normalizer: NormalizerPort | None = None,
    tenants: InMemoryTenantResolver | None = None,
    dedup: InMemoryDeduplication | None = None,
    bus: InMemoryEventBus | None = None,
) -> WebhookReceiver:
    """Receiver con secretos fijos y dobles; por defecto usa el parser real de WhatsApp.

    Args:
        normalizer: Adaptador de normalización (por defecto `MetaChannel`).
        tenants: Doble de mapeo canal→tenant.
        dedup: Doble de deduplicación.
        bus: Doble de bus de eventos.

    Returns:
        El receptor listo para `receive`.
    """
    return WebhookReceiver(
        verify_token=_TOKEN,
        app_secret=_SECRETO,
        normalizer=normalizer if normalizer is not None else MetaChannel(),
        tenants=tenants if tenants is not None else InMemoryTenantResolver(_MAPA),
        dedup=dedup if dedup is not None else InMemoryDeduplication(),
        bus=bus if bus is not None else InMemoryEventBus(),
    )


def test_meta_channel_cumple_normalizer_port() -> None:
    """El adaptador real satisface el port que inyecta la aplicación (DI estructural)."""
    assert isinstance(MetaChannel(), NormalizerPort)


def test_evento_valido_normaliza_resolve_y_encola() -> None:
    """El camino feliz: firma → parser real → tenant → un evento en la cola."""
    cuerpo = _payload_wa()
    bus = InMemoryEventBus()
    respuesta = _receptor(bus=bus).receive(raw_body=cuerpo, signature=_firma(cuerpo))
    assert (respuesta.status, respuesta.body) == (200, "EVENT_RECEIVED")
    assert len(bus.published) == 1
    nombre, payload = bus.published[0]
    assert nombre == "inbound.message"
    assert payload["tenant_id"] == _TENANT
    assert payload["channel"] == "whatsapp"
    assert payload["customer_id"] == "573001112222"
    assert payload["message_id"] == "wamid.1"
    assert payload["message_type"] == "text"
    assert payload["text"] == "hola"
    assert payload["raw_payload"] == cuerpo.decode("utf-8")
    assert isinstance(payload["correlation_id"], str)
    assert len(str(payload["correlation_id"])) == 32


def test_reenvio_del_mismo_mensaje_se_descarta_como_duplicado() -> None:
    """Meta reintenta webhooks: la segunda vez no se vuelve a encolar nada."""
    cuerpo = _payload_wa()
    bus = InMemoryEventBus()
    receptor = _receptor(bus=bus)
    receptor.receive(raw_body=cuerpo, signature=_firma(cuerpo))
    with pytest.raises(DuplicateMessageError):
        receptor.receive(raw_body=cuerpo, signature=_firma(cuerpo))
    assert len(bus.published) == 1


def test_solo_encola_los_mensajes_nuevos_del_envelope() -> None:
    """Un envelope con un duplicado y uno nuevo: encola el nuevo y acusa 200."""
    cuerpo = _payload_wa(
        mensajes=[
            {
                "from": "573001112222",
                "id": "wamid.1",
                "timestamp": "1712345678",
                "type": "text",
                "text": {"body": "hola"},
            },
            {
                "from": "573001112222",
                "id": "wamid.2",
                "timestamp": "1712345679",
                "type": "text",
                "text": {"body": "segundo"},
            },
        ]
    )
    dedup = InMemoryDeduplication()
    dedup.register_once(tenant_id=_TENANT, message_id="wamid.1")
    bus = InMemoryEventBus()
    respuesta = _receptor(dedup=dedup, bus=bus).receive(raw_body=cuerpo, signature=_firma(cuerpo))
    assert (respuesta.status, respuesta.body) == (200, "EVENT_RECEIVED")
    assert [payload["message_id"] for _, payload in bus.published] == ["wamid.2"]


def test_emisor_sin_mapeo_acusa_tenant_unknown_sin_encolar() -> None:
    """Comercio no configurado: se acusa a Meta y jamás se invoca al agente."""
    cuerpo = _payload_wa()
    bus = InMemoryEventBus()
    receptor = _receptor(tenants=InMemoryTenantResolver(), bus=bus)
    respuesta = receptor.receive(raw_body=cuerpo, signature=_firma(cuerpo))
    assert (respuesta.status, respuesta.body) == (200, "EVENT_TENANT_UNKNOWN")
    assert bus.published == []


def test_un_emisor_sin_mapeo_deja_el_envelope_completo_sin_encolar() -> None:
    """Si algún mensaje del evento no tiene mapeo, no se encola NADA del envelope."""
    mensajes = [
        ChannelMessage(
            channel="whatsapp",
            emitter_id="1000",
            customer_id="573001112222",
            message_id="wamid.1",
            timestamp=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
            message_type="text",
            text="hola",
        ),
        ChannelMessage(
            channel="whatsapp",
            emitter_id="9999",
            customer_id="573001112222",
            message_id="wamid.2",
            timestamp=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
            message_type="text",
            text="hola",
        ),
    ]
    cuerpo = _payload_wa()
    bus = InMemoryEventBus()
    receptor = _receptor(normalizer=InMemoryChannel(normalized=mensajes), bus=bus)
    respuesta = receptor.receive(raw_body=cuerpo, signature=_firma(cuerpo))
    assert (respuesta.status, respuesta.body) == (200, "EVENT_TENANT_UNKNOWN")
    assert bus.published == []


def test_encolado_fallido_libera_la_dedup_para_el_reintento() -> None:
    """Si SQS falla, la clave de dedup se libera: el reintento de Meta no se pierde."""
    cuerpo = _payload_wa()
    dedup = InMemoryDeduplication()
    receptor_falla = _receptor(
        dedup=dedup,
        bus=InMemoryEventBus(fail_with=ToolError("sqs no disponible")),
    )
    with pytest.raises(ToolError):
        receptor_falla.receive(raw_body=cuerpo, signature=_firma(cuerpo))
    bus_ok = InMemoryEventBus()
    receptor_ok = _receptor(dedup=dedup, bus=bus_ok)
    respuesta = receptor_ok.receive(raw_body=cuerpo, signature=_firma(cuerpo))
    assert (respuesta.status, respuesta.body) == (200, "EVENT_RECEIVED")
    assert len(bus_ok.published) == 1


def test_cada_mensaje_de_un_envelope_comparte_un_correlation_id_distinto() -> None:
    """Dos mensajes del mismo evento: correlación propia por mensaje, no global."""
    cuerpo = _payload_wa(
        mensajes=[
            {
                "from": "573001112222",
                "id": "wamid.1",
                "timestamp": "1712345678",
                "type": "text",
                "text": {"body": "uno"},
            },
            {
                "from": "573001112222",
                "id": "wamid.2",
                "timestamp": "1712345679",
                "type": "text",
                "text": {"body": "dos"},
            },
        ]
    )
    bus = InMemoryEventBus()
    _receptor(bus=bus).receive(raw_body=cuerpo, signature=_firma(cuerpo))
    correlaciones = [str(payload["correlation_id"]) for _, payload in bus.published]
    assert len(correlaciones) == 2
    assert len(set(correlaciones)) == 2


def test_canal_desconocido_sigue_ignorandose_antes_de_resolver() -> None:
    """El orden importa: sin canal no hay parser, tenant ni cola."""
    cuerpo = b'{"object":"unknown_platform"}'
    bus = InMemoryEventBus()
    respuesta = _receptor(bus=bus).receive(raw_body=cuerpo, signature=_firma(cuerpo))
    assert (respuesta.status, respuesta.body) == (200, "EVENT_IGNORED")
    assert bus.published == []
