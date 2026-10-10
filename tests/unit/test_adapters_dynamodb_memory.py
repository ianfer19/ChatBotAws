"""`DynamoDBMemoryStore`: `MemoryStorePort` sobre DynamoDB (Paso 8).

Prueban el adapter con un cliente falso inyectado (sin AWS real): claves con los
prefijos de DATA_MODEL, TTL calculado y comprobado, traducción de errores de
botocore a `ToolError`/`ToolTimeoutError`, validaciones de entrada y que el
payload jamás aparece en los logs.
"""

import time
from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from adapters.dynamodb import DynamoDBMemoryStore
from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.ports import MemoryStorePort

TENANT = "Sede_Elite_01"
CONVERSACION = "whatsapp:57300111111"
TABLA = "chatbot_checkpoints_dev"
PAYLOAD = '{"v": 1, "checkpoint": "secreto-del-turno"}'


class _ClienteFalso:
    """Doble del cliente `dynamodb`: registra las llamadas y devuelve lo configurado."""

    def __init__(self) -> None:
        """Prepara el doble sin llamadas y sin ítem que devolver."""
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.item: dict[str, Any] | None = None
        self.falla: Exception | None = None

    def _fallar(self) -> None:
        """Lanza la excepción configurada, si la hay.

        Raises:
            Exception: La excepción inyectada por el test (ClientError o timeout).
        """
        if self.falla is not None:
            raise self.falla

    def put_item(self, *, TableName: str, Item: dict[str, Any]) -> dict[str, Any]:
        """Registra la escritura (o falla si el test lo pidió).

        Args:
            TableName: Tabla destino.
            Item: Ítem que se escribiría.

        Returns:
            Respuesta vacía de DynamoDB.
        """
        self._fallar()
        self.puts.append({"TableName": TableName, "Item": Item})
        return {}

    def get_item(
        self, *, TableName: str, Key: dict[str, Any], ConsistentRead: bool = False
    ) -> dict[str, Any]:
        """Devuelve el ítem configurado (o falla si el test lo pidió).

        Args:
            TableName: Tabla origen.
            Key: Clave pedida.
            ConsistentRead: Lectura fuerte solicitada por el adapter.

        Returns:
            `{"Item": ...}` si hay ítem; vacío si no.
        """
        self._fallar()
        self.gets.append({"TableName": TableName, "Key": Key, "ConsistentRead": ConsistentRead})
        if self.item is None:
            return {}
        return {"Item": self.item}

    def delete_item(self, *, TableName: str, Key: dict[str, Any]) -> dict[str, Any]:
        """Registra el borrado (o falla si el test lo pidió).

        Args:
            TableName: Tabla destino.
            Key: Clave del ítem.

        Returns:
            Respuesta vacía de DynamoDB.
        """
        self._fallar()
        self.deletes.append({"TableName": TableName, "Key": Key})
        return {}


def _almacen(cliente: _ClienteFalso | None = None) -> DynamoDBMemoryStore:
    """Adapter con el doble de cliente inyectado.

    Args:
        cliente: Doble a inyectar; `None` crea uno nuevo.

    Returns:
        `DynamoDBMemoryStore` listo para usar en el test.
    """
    return DynamoDBMemoryStore(table_name=TABLA, client=cliente or _ClienteFalso())


def _error_de_servicio() -> ClientError:
    """Error de negocio típico de DynamoDB (sin AWS real).

    Returns:
        `ClientError` como lo devolvería la API.
    """
    return ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
        "PutItem",
    )


def test_el_store_satisface_el_port_estructuralmente() -> None:
    """La composición real lo usa como `MemoryStorePort`: el contrato estructural cuadra."""
    store: MemoryStorePort = _almacen()
    assert isinstance(store, MemoryStorePort)


def test_put_escribe_con_los_prefijos_de_data_model() -> None:
    """Cada ítem va en `ORG#<tenant>` / `CONV#<conv>` con su payload opaco."""
    cliente = _ClienteFalso()
    _almacen(cliente).put(
        tenant_id=TENANT, conversation_id=CONVERSACION, payload=PAYLOAD, ttl_seconds=3600
    )
    assert len(cliente.puts) == 1
    escritura = cliente.puts[0]
    assert escritura["TableName"] == TABLA
    item = escritura["Item"]
    assert item["PK"] == f"ORG#{TENANT}"
    assert item["SK"] == f"CONV#{CONVERSACION}"
    assert item["payload"] == PAYLOAD
    assert item["ttl"] > int(time.time()) + 3500


def test_put_sin_ttl_no_escribe_el_atributo() -> None:
    """`ttl_seconds=None` deja el checkpoint sin expiración (retención → ADR 0007)."""
    cliente = _ClienteFalso()
    _almacen(cliente).put(tenant_id=TENANT, conversation_id=CONVERSACION, payload=PAYLOAD)
    item = cliente.puts[0]["Item"]
    assert "ttl" not in item


def test_put_con_ttl_negativo_falla() -> None:
    """Un TTL negativo no tiene significado: se rechaza antes de escribir."""
    with pytest.raises(ValidationError):
        _almacen().put(
            tenant_id=TENANT, conversation_id=CONVERSACION, payload=PAYLOAD, ttl_seconds=-1
        )


def test_los_ids_vacios_se_rechazan() -> None:
    """Sin tenant o sin conversación no hay clave: validación en el origen."""
    store = _almacen()
    with pytest.raises(ValidationError):
        store.put(tenant_id="", conversation_id=CONVERSACION, payload=PAYLOAD)
    with pytest.raises(ValidationError):
        store.put(tenant_id=TENANT, conversation_id="", payload=PAYLOAD)
    with pytest.raises(ValidationError):
        store.get(tenant_id="", conversation_id=CONVERSACION)
    with pytest.raises(ValidationError):
        store.delete(tenant_id=TENANT, conversation_id="")


def test_la_tabla_vacia_falla_al_construir() -> None:
    """Fail fast de composición: sin tabla no hay dónde guardar el checkpoint."""
    with pytest.raises(ValidationError):
        DynamoDBMemoryStore(table_name="")


def test_get_devuelve_el_payload_con_lectura_fuerte() -> None:
    """La lectura es fuerte (no ver un checkpoint viejo) y devuelve el payload."""
    cliente = _ClienteFalso()
    cliente.item = {"PK": f"ORG#{TENANT}", "SK": f"CONV#{CONVERSACION}", "payload": PAYLOAD}
    assert _almacen(cliente).get(tenant_id=TENANT, conversation_id=CONVERSACION) == PAYLOAD
    assert cliente.gets[0]["ConsistentRead"] is True


def test_get_sin_item_devuelve_none() -> None:
    """Conversación nueva o borrada: `None`, nunca una excepción."""
    assert _almacen().get(tenant_id=TENANT, conversation_id=CONVERSACION) is None


def test_get_con_ttl_vencido_devuelve_none() -> None:
    """DynamoDB borra de forma asíncrona: el adapter también comprueba el TTL."""
    cliente = _ClienteFalso()
    cliente.item = {"payload": PAYLOAD, "ttl": int(time.time()) - 10}
    assert _almacen(cliente).get(tenant_id=TENANT, conversation_id=CONVERSACION) is None


def test_get_sin_payload_texto_falla() -> None:
    """Un ítem corrupto no se devuelve como si fuera válido: error tipado."""
    cliente = _ClienteFalso()
    cliente.item = {"payload": 42}
    with pytest.raises(ToolError):
        _almacen(cliente).get(tenant_id=TENANT, conversation_id=CONVERSACION)


def test_delete_borra_por_la_misma_clave() -> None:
    """El borrado (cierre de sesión / `/reset`) usa la clave canónica."""
    cliente = _ClienteFalso()
    _almacen(cliente).delete(tenant_id=TENANT, conversation_id=CONVERSACION)
    assert cliente.deletes == [
        {"TableName": TABLA, "Key": {"PK": f"ORG#{TENANT}", "SK": f"CONV#{CONVERSACION}"}}
    ]


def test_error_de_servicio_se_traduce_a_tool_error() -> None:
    """Nunca se fuga `ClientError` al dominio: se convierte en `ToolError` con código."""
    cliente = _ClienteFalso()
    cliente.falla = _error_de_servicio()
    store = _almacen(cliente)
    with pytest.raises(ToolError) as excinfo:
        store.put(tenant_id=TENANT, conversation_id=CONVERSACION, payload=PAYLOAD)
    assert excinfo.value.details["codigo"] == "ProvisionedThroughputExceededException"
    assert isinstance(excinfo.value.__cause__, ClientError)


def test_timeout_de_lectura_se_traduce_a_tool_timeout_error() -> None:
    """Timeout de red → `ToolTimeoutError` (el turno no se cuelga)."""
    cliente = _ClienteFalso()
    cliente.falla = ConnectTimeoutError(endpoint_url="https://dynamodb.us-east-1.amazonaws.com")
    with pytest.raises(ToolTimeoutError):
        _almacen(cliente).get(tenant_id=TENANT, conversation_id=CONVERSACION)


def test_los_logs_nunca_llevan_el_payload(caplog: pytest.LogCaptureFixture) -> None:
    """El checkpoint contiene la conversación entera: en logs solo van los ids."""
    cliente = _ClienteFalso()
    with caplog.at_level("INFO"):
        _almacen(cliente).put(
            tenant_id=TENANT, conversation_id=CONVERSACION, payload=PAYLOAD, ttl_seconds=60
        )
    assert any("dynamodb.checkpoint_put" in record.getMessage() for record in caplog.records)
    assert all(PAYLOAD not in record.getMessage() for record in caplog.records)
