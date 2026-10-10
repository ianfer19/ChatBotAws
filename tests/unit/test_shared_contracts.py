"""Tests del kernel: contratos entre slices con round-trip (shared/contracts)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from shared.contracts import (
    CustomerContext,
    InboundMessage,
    OutboundMessage,
    QueuedMessage,
    RoutedTurn,
)


def _inbound(**overrides: object) -> InboundMessage:
    """`InboundMessage` sintético válido, sobreescribible por test."""
    data: dict[str, object] = {
        "tenant_id": "Sede_Elite_01",
        "correlation_id": "corr-0001",
        "channel": "whatsapp",
        "emitter_id": "1000",
        "customer_id": "57300111111",
        "message_id": "wamid.ABC123",
        "timestamp": datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
        "text": "hola, ¿tienen mesa para 4?",
    }
    data.update(overrides)
    return InboundMessage.model_validate(data)


def test_inbound_round_trip() -> None:
    """Serializar y validar de nuevo devuelve el mismo mensaje (JSON -> modelo)."""
    message = _inbound()
    payload = message.model_dump(mode="json")
    assert InboundMessage.model_validate(payload) == message


def test_inbound_rechaza_campos_desconocidos() -> None:
    """`extra=forbid`: lo que no pasa el contrato no se encola (defensa en profundidad)."""
    data = _inbound().model_dump(mode="json")
    data["campo_raro"] = "no previsto"
    with pytest.raises(PydanticValidationError):
        InboundMessage.model_validate(data)


def test_inbound_rechaza_canal_invalido() -> None:
    """Solo los tres canales Meta (ADR 0009)."""
    with pytest.raises(PydanticValidationError):
        _inbound(channel="telegram")


def test_inbound_rechaza_texto_sobre_el_limite() -> None:
    """El threat model fija 4096 caracteres; más allá, se descarta en el gateway."""
    with pytest.raises(PydanticValidationError):
        _inbound(text="x" * 4097)


def test_inbound_permite_mensaje_sin_texto() -> None:
    """Mensaje solo media (delegado a `media_handling`): `text` puede ser `None`."""
    message = _inbound(text=None)
    assert message.text is None


def test_outbound_round_trip() -> None:
    """La respuesta hacia el canal también viaja como contrato validado."""
    outbound = OutboundMessage(
        tenant_id="Sede_Elite_01",
        correlation_id="corr-0001",
        channel="whatsapp",
        emitter_id="1000",
        customer_id="57300111111",
        text="¡Hola! Claro, te ayudo.",
    )
    assert OutboundMessage.model_validate(outbound.model_dump(mode="json")) == outbound


def test_routed_turn_conserva_ids_y_rechaza_intencion_desconocida() -> None:
    """El turno enrutado siempre arrastra tenant/correlación; la intención es un Literal."""
    turn = RoutedTurn(message=_inbound(), intent="sales", target="sales")
    assert turn.message.tenant_id == "Sede_Elite_01"
    assert turn.message.correlation_id == "corr-0001"
    assert RoutedTurn.model_validate(turn.model_dump(mode="json")) == turn
    with pytest.raises(PydanticValidationError):
        RoutedTurn.model_validate({**turn.model_dump(mode="json"), "intent": "hacking"})


def test_customer_context_round_trip_sin_verdad_operacional() -> None:
    """El contexto del cliente solo lleva identificación y preferencias."""
    context = CustomerContext(
        tenant_id="Sede_Elite_01",
        customer_id="57300111111",
        name="María",
        preferences={"idioma": "es", "mesa": "terraza"},
        tags=["vip"],
        last_seen_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )
    payload = context.model_dump(mode="json")
    assert CustomerContext.model_validate(payload) == context
    assert "precios" not in payload
    assert set(payload) == {
        "schema_version",
        "tenant_id",
        "customer_id",
        "name",
        "preferences",
        "tags",
        "last_seen_at",
    }


def test_queued_message_round_trip_con_media_y_payload() -> None:
    """La cola conserva lo que InboundMessage no trae: tipo, media y payload crudo."""
    queued = QueuedMessage(
        **_inbound(text=None).model_dump(),
        message_type="image",
        sender_name="Ana",
        media_id="MEDIA_1",
        media_type="image",
        raw_payload='{"object":"whatsapp_business_account"}',
    )
    payload = queued.model_dump(mode="json")
    assert QueuedMessage.model_validate(payload) == queued
    assert payload["media_id"] == "MEDIA_1"
    assert payload["raw_payload"].startswith("{")


def test_queued_message_sigue_siendo_inbound_para_el_supervisor() -> None:
    """El consumer entrega la cola al pipeline como InboundMessage compatible."""
    queued = QueuedMessage(
        **_inbound().model_dump(),
        raw_payload='{"object":"page"}',
    )
    assert isinstance(queued, InboundMessage)
    solo_inbound = queued.model_dump(
        mode="json",
        exclude={
            "message_type",
            "sender_name",
            "media_id",
            "media_type",
            "media_url",
            "raw_payload",
        },
    )
    reconstruido = InboundMessage.model_validate(solo_inbound)
    assert (reconstruido.tenant_id, reconstruido.message_id) == (
        queued.tenant_id,
        queued.message_id,
    )


def test_queued_message_exige_raw_payload() -> None:
    """Sin payload crudo no hay fila de mensajes que persistir: contrato lo rechaza."""
    data = _inbound().model_dump(mode="json")
    with pytest.raises(PydanticValidationError):
        QueuedMessage.model_validate(data)
    with pytest.raises(PydanticValidationError):
        QueuedMessage.model_validate({**data, "raw_payload": ""})


def test_queued_message_rechaza_campos_desconocidos() -> None:
    """Igual que el resto de contratos: lo que no está en el esquema no se encola."""
    data = {
        **_inbound().model_dump(mode="json"),
        "raw_payload": "{}",
        "campos_extra": "no",
    }
    with pytest.raises(PydanticValidationError):
        QueuedMessage.model_validate(data)
