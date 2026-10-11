"""`DynamoConversationStore`: `chatbot_conversations` del consumer (Paso 9, Fase 6).

Prueban el adapter con una tabla falsa inyectada (sin AWS real): claves de DATA_MODEL
(`ORG#`/`MSG#`), dos ítems por turno (`user`+`assistant`), ventana limitada y en orden
cronológico, aislamiento por tenant, traducción de errores de botocore y validaciones
de entrada.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from adapters.dynamodb import DynamoConversationStore
from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.ports import LLMMessage

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Otro_Comercio"
CONVERSACION = "whatsapp:57300111111"
CORRELACION = "corr-1"
TABLA = "chatbot_conversations_dev"
MOMENTO = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


class _TablaFalsa:
    """Doble de `Table`: registra `put_item` y devuelve lo configurado en `query`."""

    name: str = TABLA

    def __init__(self) -> None:
        """Prepara la tabla sin escrituras, sin ítems y sin fallo."""
        self.puts: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []
        self.falla: Exception | None = None

    def _fallar(self) -> None:
        """Lanza la excepción configurada, si la hay.

        Raises:
            Exception: La excepción inyectada por el test.
        """
        if self.falla is not None:
            raise self.falla

    def put_item(self, *, Item: Mapping[str, Any]) -> dict[str, Any]:
        """Registra la escritura (o falla si el test lo pidió).

        Args:
            Item: Ítem que se escribiría.

        Returns:
            Respuesta vacía de DynamoDB.
        """
        self._fallar()
        self.puts.append(dict(Item))
        return {}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        """Registra la consulta y devuelve los ítems configurados.

        Args:
            **kwargs: Parámetros de la consulta (TableName, KeyConditionExpression...).

        Returns:
            `{"Items": [...]}` con los ítems fijados por el test.
        """
        self._fallar()
        self.queries.append(kwargs)
        return {"Items": list(self.items)}


def _store(tabla: _TablaFalsa | None = None, **kwargs: Any) -> DynamoConversationStore:
    """Adapter con la tabla falsa inyectada.

    Args:
        tabla: Doble a inyectar; `None` crea uno nuevo.
        **kwargs: Extras para el constructor (p. ej. `ventana=4`).

    Returns:
        `DynamoConversationStore` listo para el test.
    """
    return DynamoConversationStore(table_name=TABLA, table=tabla or _TablaFalsa(), **kwargs)


def _error_servicio() -> ClientError:
    """Error de negocio típico de DynamoDB (sin AWS real).

    Returns:
        `ClientError` con código de throttling.
    """
    return ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
        "PutItem",
    )


def _persistir(store: DynamoConversationStore, *, tenant: str = TENANT) -> None:
    """Persiste un turno de prueba completo.

    Args:
        store: Adapter bajo prueba.
        tenant: Comercio dueño del turno.
    """
    store.persistir_turno(
        tenant_id=tenant,
        conversation_id=CONVERSACION,
        correlation_id=CORRELACION,
        texto_usuario="hola",
        texto_asistente="buenas",
        momento=MOMENTO,
    )


def test_persistir_turno_escribe_dos_items_con_las_claves_de_data_model() -> None:
    """Cada turno genera `user` + `assistant` con `PK=ORG#` y `SK=MSG#<conv>#<iso>#<rol>`."""
    tabla = _TablaFalsa()
    _persistir(_store(tabla))
    assert len(tabla.puts) == 2
    user, assistant = tabla.puts
    assert user["PK"] == f"ORG#{TENANT}"
    assert user["SK"].startswith(f"MSG#{CONVERSACION}#")
    assert user["role"] == "user"
    assert user["text"] == "hola"
    assert user["correlation_id"] == CORRELACION
    assert user["ttl"] > int(MOMENTO.timestamp())
    assert assistant["role"] == "assistant"
    assert assistant["text"] == "buenas"
    assert assistant["SK"].endswith("#assistant")


def test_persistir_turno_con_ids_vacios_falla() -> None:
    """Sin tenant, conversación o correlación no hay clave: validación en el origen."""
    store = _store()
    with pytest.raises(ValidationError):
        store.persistir_turno(
            tenant_id="",
            conversation_id=CONVERSACION,
            correlation_id=CORRELACION,
            texto_usuario="hola",
            texto_asistente="buenas",
            momento=MOMENTO,
        )
    with pytest.raises(ValidationError):
        store.persistir_turno(
            tenant_id=TENANT,
            conversation_id="",
            correlation_id=CORRELACION,
            texto_usuario="hola",
            texto_asistente="buenas",
            momento=MOMENTO,
        )


def test_persistir_turno_sin_texto_falla() -> None:
    """Un turno sin texto de usuario o de asistente no se persiste."""
    store = _store()
    with pytest.raises(ValidationError):
        store.persistir_turno(
            tenant_id=TENANT,
            conversation_id=CONVERSACION,
            correlation_id=CORRELACION,
            texto_usuario="",
            texto_asistente="buenas",
            momento=MOMENTO,
        )


def test_historial_devuelve_ventana_en_orden_cronologico() -> None:
    """La consulta es ascendente y limitada a `ventana * 2` (dos ítems por turno)."""
    tabla = _TablaFalsa()
    tabla.items = [
        {"role": "user", "text": "hola"},
        {"role": "assistant", "text": "buenas"},
    ]
    mensajes = _store(tabla).historial(tenant_id=TENANT, conversation_id=CONVERSACION)
    assert mensajes == [
        LLMMessage(role="user", content="hola"),
        LLMMessage(role="assistant", content="buenas"),
    ]
    consulta = tabla.queries[0]
    assert consulta["TableName"] == TABLA
    assert consulta["ScanIndexForward"] is True
    assert consulta["ExpressionAttributeValues"][":pk"] == f"ORG#{TENANT}"
    assert consulta["KeyConditionExpression"].startswith("PK = :pk AND begins_with(SK, :sk)")


def test_historial_recorta_a_la_ventana_por_si_hay_items_de_mas() -> None:
    """Aunque la tabla devuelva más ítems, el clasificador no ve más allá de la ventana."""
    tabla = _TablaFalsa()
    tabla.items = [{"role": "user", "text": f"m{i}"} for i in range(10)]
    mensajes = _store(tabla, ventana=4).historial(tenant_id=TENANT, conversation_id=CONVERSACION)
    assert [m.content for m in mensajes] == ["m6", "m7", "m8", "m9"]
    assert tabla.queries[0]["Limit"] == 8


def test_historial_sin_items_devuelve_vacio() -> None:
    """Cliente nuevo o conversación sin mensajes: lista vacía, nunca una excepción."""
    assert _store().historial(tenant_id=TENANT, conversation_id=CONVERSACION) == []


def test_historial_aislado_por_tenant() -> None:
    """La clave siempre lleva el tenant: un comercio jamás lee el de otro."""
    tabla = _TablaFalsa()
    _persistir(_store(tabla), tenant=OTRO_TENANT)
    # Simulamos que la tabla solo contiene los ítems del otro tenant.
    tabla.items = []
    _store(tabla).historial(tenant_id=TENANT, conversation_id=CONVERSACION)
    assert tabla.queries[0]["ExpressionAttributeValues"][":pk"] == f"ORG#{TENANT}"


def test_historial_sin_tenant_o_conversacion_falla() -> None:
    """Sin tenant o sin conversación no hay partición que consultar."""
    store = _store()
    with pytest.raises(ValidationError):
        store.historial(tenant_id="", conversation_id=CONVERSACION)
    with pytest.raises(ValidationError):
        store.historial(tenant_id=TENANT, conversation_id="")


def test_historial_con_ventana_invalida_falla() -> None:
    """Una ventana menor que 1 no tiene significado."""
    with pytest.raises(ValidationError):
        _store().historial(tenant_id=TENANT, conversation_id=CONVERSACION, ventana=0)


def test_historial_con_item_corrupto_falla() -> None:
    """Un ítem con `role` desconocido o sin texto no se devuelve como si fuera válido."""
    tabla = _TablaFalsa()
    tabla.items = [{"role": "system", "text": "no valido"}]
    with pytest.raises(ToolError):
        _store(tabla).historial(tenant_id=TENANT, conversation_id=CONVERSACION)


def test_error_de_servicio_se_traduce_a_tool_error() -> None:
    """Nunca se fuga `ClientError` al dominio: se convierte en `ToolError` con código."""
    tabla = _TablaFalsa()
    tabla.falla = _error_servicio()
    store = _store(tabla)
    with pytest.raises(ToolError) as excinfo:
        store.persistir_turno(
            tenant_id=TENANT,
            conversation_id=CONVERSACION,
            correlation_id=CORRELACION,
            texto_usuario="hola",
            texto_asistente="buenas",
            momento=MOMENTO,
        )
    assert excinfo.value.details["codigo"] == "ProvisionedThroughputExceededException"
    assert isinstance(excinfo.value.__cause__, ClientError)


def test_timeout_de_lectura_se_traduce_a_tool_timeout_error() -> None:
    """Timeout de red → `ToolTimeoutError` (el turno no se cuelga)."""
    tabla = _TablaFalsa()
    tabla.falla = ConnectTimeoutError(endpoint_url="https://dynamodb.us-east-1.amazonaws.com")
    with pytest.raises(ToolTimeoutError):
        _store(tabla).historial(tenant_id=TENANT, conversation_id=CONVERSACION)


def test_la_tabla_vacia_o_ventana_invalida_falla_al_construir() -> None:
    """Fail fast de composición: sin tabla no hay dónde leer ni escribir."""
    with pytest.raises(ValidationError):
        DynamoConversationStore(table_name="", table=_TablaFalsa())
    with pytest.raises(ValidationError):
        DynamoConversationStore(table_name=TABLA, table=_TablaFalsa(), ventana=0)
    with pytest.raises(ValidationError):
        DynamoConversationStore(table_name=TABLA, table=_TablaFalsa(), ttl_seconds=-1)


def test_los_logs_nunca_llevan_el_texto_del_cliente(caplog: pytest.LogCaptureFixture) -> None:
    """El turno contiene el texto del cliente: en logs solo van los ids."""
    tabla = _TablaFalsa()
    with caplog.at_level("INFO"):
        _persistir(_store(tabla))
    assert any("dynamodb.conversacion_persistida" in r.getMessage() for r in caplog.records)
    assert all(
        "hola" not in r.getMessage() and "buenas" not in r.getMessage() for r in caplog.records
    )
