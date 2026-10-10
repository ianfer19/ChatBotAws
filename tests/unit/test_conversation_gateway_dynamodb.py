"""Tests de los adapters de DynamoDB del gateway: mapeo canal→tenant y deduplicación.

Dobles de tabla inyectados por constructor (sin AWS real): se verifican las claves
replicadas del legacy (`WA_CONFIG#…|METADATA`, `MSG_PROCESSED#…`), el TTL, la
reclamación atómica (`attribute_not_exists`) y la traducción de errores.
"""

import time
from collections.abc import Mapping
from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from shared.contracts.types import Channel
from shared.errors import TenantNotFoundError, ToolError, ToolTimeoutError, ValidationError
from slices.conversation_gateway.domain.ports import DeduplicationPort, TenantResolverPort
from slices.conversation_gateway.infrastructure.dynamodb import (
    DynamoChannelMapping,
    DynamoDeduplication,
)

_TENANT = "Sede_Elite_01"


def _client_error(codigo: str) -> ClientError:
    """Construye un `ClientError` con el código de negocio indicado.

    Args:
        codigo: Código de error de DynamoDB (p. ej. `ConditionalCheckFailedException`).

    Returns:
        La excepción tal como la devolvería botocore.
    """
    return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "Operacion")


class _TablaMapeoFalsa:
    """Doble de `TablaLectura`: devuelve el ítem configurado y registra las claves."""

    def __init__(
        self, *, item: Mapping[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        """Prepara el doble.

        Args:
            item: Ítem a devolver (`None` = no existe).
            error: Excepción a lanzar en `get_item` (fallo de red/servicio).
        """
        self.item = dict(item) if item is not None else None
        self.error = error
        self.keys: list[dict[str, str]] = []

    def get_item(self, *, Key: Mapping[str, str], ConsistentRead: bool = True) -> dict[str, Any]:
        """Registra la clave leída y devuelve el ítem o el error configurado.

        Args:
            Key: Clave solicitada (`PK` + `SK`).
            ConsistentRead: Debe ser `True` (el mapeo se acaba de crear en dev).

        Returns:
            `{"Item": ...}` o `{}`.

        Raises:
            Exception: La falla inyectada en el constructor.
        """
        assert ConsistentRead, "el mapeo de canal se lee con lectura fuerte"
        self.keys.append(dict(Key))
        if self.error is not None:
            raise self.error
        return {"Item": dict(self.item)} if self.item else {}


class _TablaDedupFalsa:
    """Doble de `TablaEscritura`: simula la condición y registra las operaciones."""

    def __init__(self, *, error: Exception | None = None) -> None:
        """Prepara el doble.

        Args:
            error: Excepción a lanzar en `put_item` (`None` = escritura correcta).
        """
        self.error = error
        self.puts: list[tuple[dict[str, Any], str]] = []
        self.deletes: list[dict[str, str]] = []

    def put_item(self, *, Item: Mapping[str, Any], ConditionExpression: str = "") -> dict[str, Any]:
        """Registra el ítem y la condición; `None` simula «ya existía».

        Args:
            Item: Ítem a escribir.
            ConditionExpression: Condición atómica enviada.

        Returns:
            Respuesta vacía de éxito.

        Raises:
            Exception: La falla inyectada en el constructor.
        """
        self.puts.append((dict(Item), ConditionExpression))
        if self.error is not None:
            raise self.error
        return {}

    def delete_item(self, *, Key: Mapping[str, str]) -> dict[str, Any]:
        """Registra la clave borrada.

        Args:
            Key: Clave del ítem a borrar.

        Returns:
            Respuesta vacía de éxito.
        """
        self.deletes.append(dict(Key))
        return {}


# --- DynamoChannelMapping ------------------------------------------------------------------


def test_mapeo_resuelve_store_id_con_la_clave_del_legacy() -> None:
    """PK `WA_CONFIG#<phone_number_id>` + SK `METADATA` → `store_id` (orchestrator.py:97)."""
    tabla = _TablaMapeoFalsa(item={"store_id": _TENANT})
    mapping = DynamoChannelMapping(table_name="chatbot_channel_mapping_dev", table=tabla)
    assert mapping.resolve(channel="whatsapp", emitter_id="1000") == _TENANT
    assert tabla.keys == [{"PK": "WA_CONFIG#1000", "SK": "METADATA"}]


@pytest.mark.parametrize(
    ("channel", "prefijo"),
    [("instagram", "IG_CONFIG"), ("messenger", "FB_CONFIG")],
)
def test_mapeo_usa_el_prefijo_de_cada_canal(*, channel: Channel, prefijo: str) -> None:
    """Instagram y Messenger usan sus claves propias (ADR 0009, mismo mapeo)."""
    tabla = _TablaMapeoFalsa(item={"store_id": _TENANT})
    mapping = DynamoChannelMapping(table_name="chatbot_channel_mapping_dev", table=tabla)
    assert mapping.resolve(channel=channel, emitter_id="PAGE_1") == _TENANT
    assert tabla.keys[0]["PK"] == f"{prefijo}#PAGE_1"


def test_mapeo_sin_item_es_tenant_not_found() -> None:
    """Sin fila no hay comercio: el webhook acusa `EVENT_TENANT_UNKNOWN`."""
    mapping = DynamoChannelMapping(
        table_name="chatbot_channel_mapping_dev",
        table=_TablaMapeoFalsa(),
    )
    with pytest.raises(TenantNotFoundError):
        mapping.resolve(channel="whatsapp", emitter_id="1000")


def test_mapeo_con_item_malformado_tambien_es_tenant_not_found() -> None:
    """Un ítem sin `store_id` no revela internos: mismo resultado que «sin mapeo»."""
    mapping = DynamoChannelMapping(
        table_name="chatbot_channel_mapping_dev",
        table=_TablaMapeoFalsa(item={"algo": "otro"}),
    )
    with pytest.raises(TenantNotFoundError):
        mapping.resolve(channel="whatsapp", emitter_id="1000")


def test_mapeo_sin_emitter_es_validation_error() -> None:
    """Un emisor vacío es payload malformado, no un tenant inexistente."""
    mapping = DynamoChannelMapping(
        table_name="chatbot_channel_mapping_dev",
        table=_TablaMapeoFalsa(item={"store_id": _TENANT}),
    )
    with pytest.raises(ValidationError):
        mapping.resolve(channel="whatsapp", emitter_id="")


def test_mapeo_sin_tabla_es_validation_error() -> None:
    """Fail fast de composición: sin tabla no se crea el adapter."""
    with pytest.raises(ValidationError):
        DynamoChannelMapping(table_name="")


def test_mapeo_traduce_timeout_y_client_error() -> None:
    """Los errores de botocore jamás llegan a la aplicación sin traducir."""
    timing_out = DynamoChannelMapping(
        table_name="chatbot_channel_mapping_dev",
        table=_TablaMapeoFalsa(error=ConnectTimeoutError(endpoint_url="https://dynamodb")),
    )
    with pytest.raises(ToolTimeoutError):
        timing_out.resolve(channel="whatsapp", emitter_id="1000")
    fallando = DynamoChannelMapping(
        table_name="chatbot_channel_mapping_dev",
        table=_TablaMapeoFalsa(error=_client_error("ProvisionedThroughputExceededException")),
    )
    with pytest.raises(ToolError):
        fallando.resolve(channel="whatsapp", emitter_id="1000")


def test_mapeo_cumple_tenant_resolver_port() -> None:
    """Satisface estructuralmente el port del dominio (DI sin herencia)."""
    mapping = DynamoChannelMapping(
        table_name="chatbot_channel_mapping_dev",
        table=_TablaMapeoFalsa(item={"store_id": _TENANT}),
    )
    assert isinstance(mapping, TenantResolverPort)


# --- DynamoDeduplication --------------------------------------------------------------------


def test_dedup_reclama_con_clave_por_tenant_y_ttl_de_24h() -> None:
    """`MSG_PROCESSED#<message_id>` + `SK = DEDUP#<tenant>` con condición atómica."""
    tabla = _TablaDedupFalsa()
    dedup = DynamoDeduplication(table_name="chatbot_processed_messages_dev", table=tabla)
    assert dedup.register_once(tenant_id=_TENANT, message_id="wamid.1") is True
    ((item, condicion),) = tabla.puts
    assert item["PK"] == "MSG_PROCESSED#wamid.1"
    assert item["SK"] == f"DEDUP#{_TENANT}"
    assert condicion == "attribute_not_exists(PK)"
    assert item["ttl"] - item["processed_at"] == 24 * 60 * 60
    assert abs(item["processed_at"] - int(time.time())) <= 5


def test_dedup_devuelve_false_si_el_ite_ya_existia() -> None:
    """`ConditionalCheckFailedException` no es error: es un duplicado normal."""
    dedup = DynamoDeduplication(
        table_name="chatbot_processed_messages_dev",
        table=_TablaDedupFalsa(error=_client_error("ConditionalCheckFailedException")),
    )
    assert dedup.register_once(tenant_id=_TENANT, message_id="wamid.1") is False


def test_dedup_traduce_otros_errores_de_dynamodb() -> None:
    """Un fallo distinto del condicional sí es error del servicio (→ 502 y retry)."""
    dedup = DynamoDeduplication(
        table_name="chatbot_processed_messages_dev",
        table=_TablaDedupFalsa(error=_client_error("InternalServerError")),
    )
    with pytest.raises(ToolError):
        dedup.register_once(tenant_id=_TENANT, message_id="wamid.1")


def test_dedup_libera_el_registro_con_la_misma_clave() -> None:
    """`release` borra exactamente lo que escribió `register_once` (rollback)."""
    tabla = _TablaDedupFalsa()
    dedup = DynamoDeduplication(table_name="chatbot_processed_messages_dev", table=tabla)
    dedup.register_once(tenant_id=_TENANT, message_id="wamid.1")
    dedup.release(tenant_id=_TENANT, message_id="wamid.1")
    assert tabla.deletes == [{"PK": "MSG_PROCESSED#wamid.1", "SK": f"DEDUP#{_TENANT}"}]


def test_dedup_sin_claves_o_con_ttl_invalido_es_validation_error() -> None:
    """La clave siempre lleva tenant y mensaje; el TTL no puede ser negativo."""
    with pytest.raises(ValidationError):
        DynamoDeduplication(table_name="", ttl_seconds=86400)
    with pytest.raises(ValidationError):
        DynamoDeduplication(table_name="tabla", ttl_seconds=-1)
    dedup = DynamoDeduplication(
        table_name="chatbot_processed_messages_dev",
        table=_TablaDedupFalsa(),
    )
    with pytest.raises(ValidationError):
        dedup.register_once(tenant_id="", message_id="wamid.1")
    with pytest.raises(ValidationError):
        dedup.release(tenant_id=_TENANT, message_id="")


def test_dedup_cumple_deduplication_port() -> None:
    """Satisface estructuralmente el port del dominio (DI sin herencia)."""
    dedup = DynamoDeduplication(
        table_name="chatbot_processed_messages_dev",
        table=_TablaDedupFalsa(),
    )
    assert isinstance(dedup, DeduplicationPort)
