"""Tests unitarios de `adapters.bedrock.BedrockEmbeddings`: cuerpo, errores y dims.

Sin AWS real: un doble de `InvokeModelClient` registra la petición y devuelve la
respuesta con la **forma exacta verificada con una invocación real** en el Paso 7
(`{"embedding": [...1536...], "inputTextTokenCount": n}` de Titan v1).
"""

import json
from typing import Any

import pytest
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

import adapters.bedrock.embeddings as embeddings_module
from adapters.bedrock import BedrockEmbeddings, InvokeModelClient
from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.ports import EmbeddingsPort

_MODELO = "amazon.titan-embed-text-v1"
_DIMS = 1536


class _CuerpoFalso:
    """Stream `body` de la respuesta (solo `read()`, como el de boto3)."""

    def __init__(self, datos: bytes) -> None:
        """Guarda los bytes que devolverá `read`.

        Args:
            datos: Cuerpo JSON ya serializado.
        """
        self._datos = datos

    def read(self) -> bytes:
        """Devuelve el cuerpo completo (boto3 lo entrega de una vez aquí)."""
        return self._datos


class _DobleInvoke:
    """Doble de `InvokeModelClient` que registra la petición y responde fijo."""

    def __init__(
        self,
        embedding: list[float] | None = None,
        error: Exception | None = None,
        sin_body: bool = False,
    ) -> None:
        """Configura la respuesta o el error que lanzará cada llamada.

        Args:
            embedding: Embedding a devolver; por defecto uno de `_DIMS` componentes.
            error: Excepción a lanzar (simula el fallo del servicio).
            sin_body: Si es `True`, la respuesta no trae `body` (forma inválida).
        """
        self.peticiones: list[dict[str, Any]] = []
        self._embedding = embedding if embedding is not None else _embedding_prueba()
        self._error = error
        self._sin_body = sin_body

    def invoke_model(
        self,
        *,
        modelId: str,
        body: bytes,
        contentType: str,
        accept: str,
    ) -> dict[str, Any]:
        """Registra la petición; lanza el error configurado o devuelve la respuesta."""
        self.peticiones.append(
            {
                "modelId": modelId,
                "body": body,
                "contentType": contentType,
                "accept": accept,
            }
        )
        if self._error is not None:
            raise self._error
        if self._sin_body:
            return {"contentType": contentType}
        payload = {"embedding": self._embedding, "inputTextTokenCount": 7}
        return {
            "body": _CuerpoFalso(json.dumps(payload).encode("utf-8")),
            "contentType": contentType,
        }


def _embedding_prueba(dim: int = _DIMS) -> list[float]:
    """Embedding sintético distinto por componente (para verificar el orden).

    Args:
        dim: Número de componentes.

    Returns:
        Lista de `dim` flotantes.
    """
    return [round(i / dim, 6) for i in range(dim)]


def _adapter(**kwargs: object) -> BedrockEmbeddings:
    """Adapter con doble inyectado y valores por defecto de test.

    Args:
        kwargs: Campos a sobreescribir del constructor.

    Returns:
        `BedrockEmbeddings` listo para usar.
    """
    campos: dict[str, Any] = {"model_id": _MODELO, "client": _DobleInvoke()}
    campos.update(kwargs)
    return BedrockEmbeddings(**campos)


def test_es_un_embeddings_port() -> None:
    """Debe satisfacer `EmbeddingsPort`: los consumidores solo ven el port."""
    assert isinstance(_adapter(), EmbeddingsPort)


def test_envia_input_text_el_modelo_y_json() -> None:
    """La petición lleva `{"inputText": ...}` y el modelo configurado (API real)."""
    doble = _DobleInvoke()
    _adapter(client=doble).embed(texts=["horario de apertura"])

    peticion = doble.peticiones[0]
    assert peticion["modelId"] == _MODELO
    assert peticion["contentType"] == "application/json"
    assert peticion["accept"] == "application/json"
    assert json.loads(peticion["body"]) == {"inputText": "horario de apertura"}


def test_una_llamada_por_texto_respetando_el_orden() -> None:
    """Titan no admite lote: N textos = N invocaciones en el mismo orden."""
    doble = _DobleInvoke()
    vectores = _adapter(client=doble).embed(texts=["uno", "dos", "tres"])

    assert [json.loads(p["body"])["inputText"] for p in doble.peticiones] == [
        "uno",
        "dos",
        "tres",
    ]
    assert len(vectores) == 3


def test_devuelve_floats_y_dimensiones_del_modelo() -> None:
    """El vector sale como `list[float]` con la dimensionalidad configurada."""
    doble = _DobleInvoke(embedding=[0.25, 0.75, 1.0])
    vectores = _adapter(client=doble, dimensions=3).embed(texts=["hola"])

    assert vectores[0] == [0.25, 0.75, 1.0]
    assert all(isinstance(valor, float) for valor in vectores[0])
    assert _adapter(client=doble, dimensions=3).dimensions == 3


def test_loguea_el_exito_sin_el_texto_del_cliente(caplog: pytest.LogCaptureFixture) -> None:
    """`bedrock.embed.ok` lleva modelo y cantidad; nunca el texto (puede ser PII)."""
    with caplog.at_level("INFO"):
        _adapter().embed(texts=["horario de apertura"])
    eventos = [record for record in caplog.records if "bedrock.embed.ok" in record.getMessage()]
    assert eventos
    assert getattr(eventos[0], "model_id", None) == _MODELO
    assert getattr(eventos[0], "texts", None) == 1
    assert "horario" not in caplog.text


def test_texts_vacio_es_validation_error() -> None:
    """Nada que vectorizar no gasta llamadas a Bedrock."""
    with pytest.raises(ValidationError):
        _adapter().embed(texts=[])


def test_texto_en_blanco_es_validation_error() -> None:
    """Un texto sin contenido tampoco llega al modelo."""
    with pytest.raises(ValidationError):
        _adapter().embed(texts=["   "])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model_id": ""},
        {"model_id": _MODELO, "dimensions": 0},
        {"model_id": _MODELO, "timeout_seconds": 0},
    ],
)
def test_configuracion_invalida_es_validation_error(kwargs: dict[str, Any]) -> None:
    """Sin modelo, con dimensiones o timeout inválidos el adapter no arranca."""
    with pytest.raises(ValidationError):
        BedrockEmbeddings(client=_DobleInvoke(), **kwargs)


def test_client_error_se_traduce_a_tool_error() -> None:
    """`botocore.ClientError` jamás se fuga: sale como `ToolError` tipado."""
    error = ClientError(
        {
            "Error": {"Code": "ThrottlingException", "Message": "slow down"},
            "ResponseMetadata": {},
        },
        "InvokeModel",
    )
    with pytest.raises(ToolError):
        _adapter(client=_DobleInvoke(error=error)).embed(texts=["hola"])


def test_timeout_de_lectura_se_traduce_a_tool_timeout_error() -> None:
    """Un timeout de lectura es `ToolTimeoutError` (el turno degrada, no rompe)."""
    error = ReadTimeoutError(endpoint_url="https://bedrock.us-east-1.amazonaws.com")
    with pytest.raises(ToolTimeoutError):
        _adapter(client=_DobleInvoke(error=error)).embed(texts=["hola"])


def test_timeout_de_conexion_se_traduce_a_tool_timeout_error() -> None:
    """Un timeout de conexión también: misma traducción que la Converse API."""
    error = ConnectTimeoutError(endpoint_url="https://bedrock.us-east-1.amazonaws.com")
    with pytest.raises(ToolTimeoutError):
        _adapter(client=_DobleInvoke(error=error)).embed(texts=["hola"])


def test_error_de_red_se_traduce_a_tool_error() -> None:
    """Cualquier `BotoCoreError` (red, región, DNS) sale como `ToolError`."""
    with pytest.raises(ToolError):
        _adapter(client=_DobleInvoke(error=BotoCoreError())).embed(texts=["hola"])


def test_respuesta_sin_body_es_tool_error() -> None:
    """Una respuesta con forma inesperada no se fuga como `KeyError`."""
    with pytest.raises(ToolError):
        _adapter(client=_DobleInvoke(sin_body=True)).embed(texts=["hola"])


def test_respuesta_sin_embedding_es_tool_error() -> None:
    """Falta `embedding` en el payload: `ToolError`, nunca un `None` al caller."""
    with pytest.raises(ToolError):
        _adapter(client=_DobleInvoke(embedding=[])).embed(texts=["hola"])


def test_embedding_no_numerico_es_tool_error() -> None:
    """Componentes no numéricos no pasan al almacén vectorial."""
    with pytest.raises(ToolError):
        _adapter(client=_DobleInvoke(embedding=["x", "y"])).embed(texts=["hola"])  # type: ignore[list-item]


def test_dimensionalidad_distinta_es_tool_error() -> None:
    """Defensa contra un modelo mal configurado: la columna pgvector no cabría."""
    with pytest.raises(ToolError) as excinfo:
        _adapter(client=_DobleInvoke(embedding=[1.0, 2.0, 3.0])).embed(texts=["hola"])
    assert "dimensionalidad" in str(excinfo.value)


def test_crea_el_cliente_real_con_el_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin cliente inyectado se crea el `bedrock-runtime` con el timeout dado."""
    captura: dict[str, Any] = {}

    def _falso_cliente(servicio: str, *, config: Any) -> _DobleInvoke:
        captura["servicio"] = servicio
        captura["connect_timeout"] = config.connect_timeout
        captura["read_timeout"] = config.read_timeout
        return _DobleInvoke()

    monkeypatch.setattr(embeddings_module.boto3, "client", _falso_cliente)
    _adapter(client=None, timeout_seconds=7)
    assert captura["servicio"] == "bedrock-runtime"
    assert captura["connect_timeout"] == 7
    assert captura["read_timeout"] == 7


def test_el_protocolo_coincide_con_boto3() -> None:
    """El doble satisface `InvokeModelClient` (la inyección del constructor)."""
    assert isinstance(_DobleInvoke(), InvokeModelClient)
