"""Tests del dominio del conversation_gateway: firma, detección de canal, dedup y dobles."""

import hashlib
import hmac
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from shared.contracts.messages import OutboundMessage
from shared.errors import AppError, TenantNotFoundError, ValidationError
from shared.ports import ChannelMessage, ChannelPort
from slices.conversation_gateway.domain.channels import detect_channel
from slices.conversation_gateway.domain.errors import (
    DuplicateMessageError,
    InvalidSignatureError,
)
from slices.conversation_gateway.domain.ports import DeduplicationPort, TenantResolverPort
from slices.conversation_gateway.domain.signature import is_valid_signature
from slices.conversation_gateway.infrastructure.in_memory import (
    InMemoryChannel,
    InMemoryDeduplication,
    InMemoryTenantResolver,
)

_SECRETO = "app-secreta-del-test"
_PAYLOAD = b'{"object":"whatsapp_business_account"}'
_AHORA = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _firma(cuerpo: bytes, secreto: str = _SECRETO) -> str:
    """Firma de prueba con el mismo algoritmo que Meta (HMAC-SHA256 con prefijo `sha256=`)."""
    return "sha256=" + hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def _mensaje_falso() -> ChannelMessage:
    """`ChannelMessage` de prueba para configurar el doble de canal."""
    return ChannelMessage(
        channel="whatsapp",
        emitter_id="1000",
        customer_id="5215512345678",
        message_id="wamid.ABC",
        timestamp=_AHORA,
    )


def _respuesta() -> OutboundMessage:
    """`OutboundMessage` de prueba para capturar en el doble de canal."""
    return OutboundMessage(
        tenant_id="Sede_Elite_01",
        correlation_id="corr-1",
        channel="whatsapp",
        customer_id="5215512345678",
        text="hola",
    )


# --- firma HMAC (regla 1 del slice) ------------------------------------------------


def test_firma_valida_es_aceptada() -> None:
    """La firma que generó Meta con el secreto correcto pasa la verificación."""
    assert is_valid_signature(payload=_PAYLOAD, signature=_firma(_PAYLOAD), app_secret=_SECRETO)


def test_firma_alterada_es_rechazada() -> None:
    """Un cuerpo o una firma manipulados no coinciden (webhook forjado)."""
    assert not is_valid_signature(
        payload=_PAYLOAD + b" ",
        signature=_firma(_PAYLOAD),
        app_secret=_SECRETO,
    )
    assert not is_valid_signature(
        payload=_PAYLOAD,
        signature=_firma(_PAYLOAD, secreto="otro-secreto"),
        app_secret=_SECRETO,
    )


def test_sin_firma_o_sin_secreto_se_rechaza() -> None:
    """Sin cabecera o sin secreto configurado no se procesa nada (a diferencia del legacy)."""
    assert not is_valid_signature(payload=_PAYLOAD, signature=None, app_secret=_SECRETO)
    assert not is_valid_signature(payload=_PAYLOAD, signature="", app_secret=_SECRETO)
    assert not is_valid_signature(payload=_PAYLOAD, signature=_firma(_PAYLOAD), app_secret="")


def test_firma_sin_prefijo_sha256_se_rechaza() -> None:
    """Meta envía siempre `sha256=<hex>`; cualquier otro formato se descarta."""
    hex_crudo = _firma(_PAYLOAD).removeprefix("sha256=")
    assert not is_valid_signature(payload=_PAYLOAD, signature=hex_crudo, app_secret=_SECRETO)
    assert not is_valid_signature(payload=_PAYLOAD, signature="md5=abc", app_secret=_SECRETO)


def test_firma_de_payload_vacio_es_valida() -> None:
    """Un cuerpo vacío firmado sigue siendo verificable (no es lo mismo que ausente)."""
    assert is_valid_signature(payload=b"", signature=_firma(b""), app_secret=_SECRETO)


# --- detección de canal desde el envelope -------------------------------------------


def test_detecta_los_tres_canales() -> None:
    """El campo `object` distingue WhatsApp, Instagram y Messenger."""
    assert detect_channel({"object": "whatsapp_business_account"}) == "whatsapp"
    assert detect_channel({"object": "instagram"}) == "instagram"
    assert detect_channel({"object": "page"}) == "messenger"


def test_envelope_desconocido_devuelve_none() -> None:
    """Un envelope que no es de los 3 canales se ignora sin error (handler → 200)."""
    assert detect_channel({"object": "unknown_platform"}) is None
    assert detect_channel({"entry": []}) is None
    assert detect_channel({}) is None
    assert detect_channel({"object": 42}) is None


# --- contrato ChannelMessage ---------------------------------------------------------


def test_channel_message_es_inmutable_y_sin_campos_extra() -> None:
    """El contrato puente no se altera tras leerse ni acepta campos ajenos."""
    mensaje = _mensaje_falso()
    with pytest.raises(PydanticValidationError):
        mensaje.text = "otro"  # pyrefly: ignore[read-only]
    with pytest.raises(PydanticValidationError):
        ChannelMessage(
            channel="whatsapp",
            emitter_id="1000",
            customer_id="5215512345678",
            message_id="wamid.ABC",
            timestamp=_AHORA,
            tenant_id="Sede_Elite_01",  # type: ignore[call-arg]
        )


def test_channel_message_rechaza_texto_mas_largo_del_limite() -> None:
    """Threat model §8: un mensaje de más de 4096 no pasa el contrato del gateway."""
    with pytest.raises(PydanticValidationError):
        ChannelMessage(
            channel="whatsapp",
            emitter_id="1000",
            customer_id="5215512345678",
            message_id="wamid.ABC",
            timestamp=_AHORA,
            text="x" * 4097,
        )


def test_channel_message_con_media_conserva_solo_atributos() -> None:
    """Media (Fase 3): solo `media_id`/`media_type`/`media_url`; sin descarga aquí."""
    mensaje = ChannelMessage(
        channel="instagram",
        emitter_id="17841400000000001",
        customer_id="12345",
        message_id="mid.7",
        timestamp=_AHORA,
        message_type="image",
        media_id="IGID",
        media_type="image/jpeg",
        media_url="https://lookaside.example/fbx2",
    )
    assert mensaje.message_type == "image"
    assert mensaje.media_id == "IGID"


def test_channel_message_defaults_desconocido_sin_media() -> None:
    """Sin clasificar, el tipo es `unknown` y la media queda vacía."""
    mensaje = _mensaje_falso()
    assert mensaje.message_type == "unknown"
    assert (mensaje.media_id, mensaje.media_type, mensaje.media_url) == (None, None, None)


# --- errores del dominio --------------------------------------------------------------


def test_errores_del_dominio_tienen_codigo_y_estado() -> None:
    """Los handlers traducen por `code`/`http_status`: 403 para firma, 200 para dup."""
    assert issubclass(InvalidSignatureError, AppError)
    assert InvalidSignatureError.code == "invalid_signature"
    assert InvalidSignatureError.http_status == 403
    assert DuplicateMessageError.code == "duplicate_message"
    assert DuplicateMessageError.http_status == 200


# --- resolución de tenant (doble) ------------------------------------------------------


def test_resolutor_devuelve_el_tenant_del_emisor() -> None:
    """El mapeo `(canal, emisor) → store_id` replica la clave `WA_CONFIG#` del legacy."""
    resolver = InMemoryTenantResolver({("whatsapp", "1000"): "Sede_Elite_01"})
    assert resolver.resolve(channel="whatsapp", emitter_id="1000") == "Sede_Elite_01"


def test_resolutor_sin_mapeo_levanta_tenant_not_found() -> None:
    """Sin mapeo no hay turno: «comercio no disponible» y jamás se invoca al supervisor."""
    resolver = InMemoryTenantResolver()
    with pytest.raises(TenantNotFoundError):
        resolver.resolve(channel="whatsapp", emitter_id="1000")


def test_resolutor_no_cruza_canales_del_mismo_emisor() -> None:
    """Un emisor registrado en WhatsApp no resuelve en Instagram (clave por canal)."""
    resolver = InMemoryTenantResolver({("whatsapp", "1000"): "Sede_Elite_01"})
    with pytest.raises(TenantNotFoundError):
        resolver.resolve(channel="instagram", emitter_id="1000")


def test_resolutor_sin_emitter_levanta_validation_error() -> None:
    """Resolver «a ciegas» es un bug: se valida la entrada."""
    resolver = InMemoryTenantResolver({("whatsapp", "1000"): "Sede_Elite_01"})
    with pytest.raises(ValidationError):
        resolver.resolve(channel="whatsapp", emitter_id="")


# --- deduplicación (doble) -------------------------------------------------------------


def test_dedup_primera_vez_true_y_segunda_false() -> None:
    """El primer registro pasa y el reenvío de Meta se detecta como duplicado."""
    dedup = InMemoryDeduplication()
    assert dedup.register_once(tenant_id="Sede_Elite_01", message_id="wamid.1") is True
    assert dedup.register_once(tenant_id="Sede_Elite_01", message_id="wamid.1") is False


def test_dedup_aisla_por_tenant() -> None:
    """El mismo `message_id` de otro comercio no se ve afectado (clave compuesta)."""
    dedup = InMemoryDeduplication()
    assert dedup.register_once(tenant_id="Sede_Elite_01", message_id="mid.1") is True
    assert dedup.register_once(tenant_id="Otro_Comercio_01", message_id="mid.1") is True


def test_dedup_sin_claves_levanta_validation_error() -> None:
    """Sin tenant o sin message_id no se registra nada."""
    dedup = InMemoryDeduplication()
    with pytest.raises(ValidationError):
        dedup.register_once(tenant_id="", message_id="wamid.1")
    with pytest.raises(ValidationError):
        dedup.register_once(tenant_id="Sede_Elite_01", message_id="")


# --- dobles cumplen los ports (DI manual) ----------------------------------------------


def test_dobles_cumplen_sus_ports() -> None:
    """La DI manual funciona: isinstance del Protocol acepta cada doble."""
    assert isinstance(InMemoryTenantResolver(), TenantResolverPort)
    assert isinstance(InMemoryDeduplication(), DeduplicationPort)
    assert isinstance(InMemoryChannel(), ChannelPort)


def test_dobles_tipados_cumplen_la_firma_estructural() -> None:
    """mypy verifica la firma completa al asignarlos al tipo del port."""
    resolver: TenantResolverPort = InMemoryTenantResolver()
    dedup: DeduplicationPort = InMemoryDeduplication()
    canal: ChannelPort = InMemoryChannel()
    assert isinstance(resolver, TenantResolverPort)
    assert isinstance(dedup, DeduplicationPort)
    assert isinstance(canal, ChannelPort)


# --- doble de canal (send / credentials / normalize) --------------------------------------


def test_canal_falso_captura_lo_enviado() -> None:
    """`send` no toca Meta: la respuesta queda lista para asertar en los tests."""
    canal = InMemoryChannel()
    canal.send(_respuesta())
    assert [m.text for m in canal.sent] == ["hola"]


def test_canal_falso_verify_credentials_es_configurable() -> None:
    """El estado de credenciales se fija en el constructor (positivo y negativo)."""
    assert InMemoryChannel().verify_credentials(channel="whatsapp", tenant_id="t1") is True
    sin_cred = InMemoryChannel(credentials_ok=False)
    assert sin_cred.verify_credentials(channel="instagram", tenant_id="t1") is False


def test_canal_falso_normalize_devuelve_lo_configurado() -> None:
    """`normalize_inbound` devuelve el mensaje fijado o `None` (evento a ignorar)."""
    mensaje = _mensaje_falso()
    assert InMemoryChannel(normalized=mensaje).normalize_inbound({}, channel="whatsapp") == mensaje
    assert InMemoryChannel().normalize_inbound({}, channel="whatsapp") is None
