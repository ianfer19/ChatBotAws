"""Tests unitarios de `adapters.bedrock.BedrockLLM`: mapeo, respuesta y errores.

Sin AWS real: un doble de `ConverseClient` registra la petición y devuelve la
respuesta que cada test necesite (regla de `adapters/AGENTS.md` nº 1).
"""

from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError, NoRegionError

import adapters.bedrock.llm as llm_module
from adapters.bedrock import BedrockLLM, ConverseClient
from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.ports import LLMMessage, LLMPort

_MODELO = "modelo-de-prueba"


class _DobleConverse:
    """Doble de `ConverseClient` que registra la petición y devuelve una respuesta fija."""

    def __init__(
        self, respuesta: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.peticiones: list[dict[str, Any]] = []
        self._respuesta = respuesta if respuesta is not None else _respuesta_ok()
        self._error = error

    def converse(
        self,
        *,
        modelId: str,
        messages: list[dict[str, Any]],
        system: list[dict[str, Any]] | None = None,
        inferenceConfig: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra la petición; lanza el error configurado o devuelve la respuesta."""
        self.peticiones.append(
            {
                "modelId": modelId,
                "messages": messages,
                "system": system,
                "inferenceConfig": inferenceConfig,
            }
        )
        if self._error is not None:
            raise self._error
        return self._respuesta


def _respuesta_ok(texto: str = "Hola, ¿en qué te ayudo?") -> dict[str, Any]:
    """Respuesta de Converse con la forma exacta del servicio (verificada en el Paso 2).

    Args:
        texto: Texto del bloque de contenido de la respuesta.

    Returns:
        dict con `output`, `stopReason` y `usage`.
    """
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": texto}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 7, "totalTokens": 19},
    }


def _mensajes() -> list[LLMMessage]:
    """Historial mínimo para las invocaciones de test."""
    return [
        LLMMessage(role="user", content="Responde solo con OK"),
        LLMMessage(role="assistant", content="OK"),
        LLMMessage(role="user", content="¿Abierto hoy?"),
    ]


def test_es_un_llm_port() -> None:
    """Debe satisfacer `LLMPort`: los consumidores solo ven el port (ADR 0004)."""
    assert isinstance(BedrockLLM(model_id=_MODELO, client=_DobleConverse()), LLMPort)


def test_mapea_modelo_historial_y_sin_system_ni_inference_config() -> None:
    """La petición lleva el `modelId` configurado y el historial rol+bloque de texto."""
    doble = _DobleConverse()
    BedrockLLM(model_id=_MODELO, client=doble).invoke(messages=_mensajes())

    peticion = doble.peticiones[0]
    assert peticion["modelId"] == _MODELO
    assert peticion["messages"] == [
        {"role": "user", "content": [{"text": "Responde solo con OK"}]},
        {"role": "assistant", "content": [{"text": "OK"}]},
        {"role": "user", "content": [{"text": "¿Abierto hoy?"}]},
    ]
    assert peticion["system"] is None
    assert peticion["inferenceConfig"] is None


def test_envia_system_e_inference_config_cuando_llegan() -> None:
    """`system` viaja como bloque aparte y `inferenceConfig` solo con lo indicado."""
    doble = _DobleConverse()
    BedrockLLM(model_id=_MODELO, client=doble).invoke(
        messages=_mensajes(),
        system="Eres un asistente de tienda.",
        max_tokens=256,
        temperature=0.2,
    )

    peticion = doble.peticiones[0]
    assert peticion["system"] == [{"text": "Eres un asistente de tienda."}]
    assert peticion["inferenceConfig"] == {"maxTokens": 256, "temperature": 0.2}


def test_parsea_respuesta_texto_stop_reason_y_tokens() -> None:
    """De la respuesta salen texto, motivo de parada y consumo de tokens."""
    resultado = BedrockLLM(model_id=_MODELO, client=_DobleConverse()).invoke(messages=_mensajes())

    assert resultado.text == "Hola, ¿en qué te ayudo?"
    assert resultado.stop_reason == "end_turn"
    assert resultado.input_tokens == 12
    assert resultado.output_tokens == 7


def test_concatena_varios_bloques_de_texto() -> None:
    """Un contenido con varios bloques se une en orden (no se pierde información)."""
    respuesta = _respuesta_ok()
    respuesta["output"]["message"]["content"] = [{"text": "Hola, "}, {"text": "¿en qué te ayudo?"}]
    resultado = BedrockLLM(model_id=_MODELO, client=_DobleConverse(respuesta=respuesta)).invoke(
        messages=_mensajes()
    )
    assert resultado.text == "Hola, ¿en qué te ayudo?"


def test_client_error_se_traduce_a_tool_error() -> None:
    """`botocore.ClientError` jamás se fuga: sale como `ToolError` con `cause` preservado."""
    error = ClientError(
        {
            "Error": {"Code": "ModelNotReadyException", "Message": "not ready"},
            "ResponseMetadata": {},
        },
        "Converse",
    )
    doble = _DobleConverse(error=error)

    with pytest.raises(ToolError) as captura:
        BedrockLLM(model_id=_MODELO, client=doble).invoke(messages=_mensajes())

    assert not isinstance(captura.value, ClientError)
    assert captura.value.__cause__ is error
    assert captura.value.details["error_code"] == "ModelNotReadyException"
    assert captura.value.details["model_id"] == _MODELO


def test_timeout_de_red_se_traduce_a_tool_timeout_error() -> None:
    """El timeout de lectura se convierte en `ToolTimeoutError`, no en excepción de botocore."""
    doble = _DobleConverse(
        error=ConnectTimeoutError(endpoint_url="https://bedrock.us-east-1.amazonaws.com")
    )

    with pytest.raises(ToolTimeoutError):
        BedrockLLM(model_id=_MODELO, timeout_seconds=5, client=doble).invoke(messages=_mensajes())


def test_error_de_cliente_boto_se_traduce_a_tool_error() -> None:
    """Cualquier otro `BotoCoreError` (p. ej. región ausente) también sale tipado."""
    doble = _DobleConverse(error=NoRegionError())

    with pytest.raises(ToolError) as captura:
        BedrockLLM(model_id=_MODELO, client=doble).invoke(messages=_mensajes())

    assert captura.value.details["error"] == "NoRegionError"


def test_respuesta_con_forma_inesperada_no_se_fuga_key_error() -> None:
    """Una respuesta ilegible se traduce en `ToolError` (contrato del port)."""
    doble = _DobleConverse(respuesta={"output": {}})

    with pytest.raises(ToolError):
        BedrockLLM(model_id=_MODELO, client=doble).invoke(messages=_mensajes())


def test_model_id_vacio_y_timeout_no_positivo_son_error_de_validacion() -> None:
    """Configuración inválida se rechaza al construir, no en la primera llamada."""
    with pytest.raises(ValidationError):
        BedrockLLM(model_id="", client=_DobleConverse())
    with pytest.raises(ValidationError):
        BedrockLLM(model_id=_MODELO, timeout_seconds=0, client=_DobleConverse())


def test_sin_cliente_inyectado_crea_el_suyo(monkeypatch: pytest.MonkeyPatch) -> None:
    """La DI no exige doble: sin `client` se construye el cliente real dentro del adapter."""
    creados: list[tuple[str, Any]] = []

    def _falso_client(servicio: str, *, config: Any) -> _DobleConverse:
        creados.append((servicio, config))
        return _DobleConverse()

    monkeypatch.setattr(llm_module.boto3, "client", _falso_client)
    llm = BedrockLLM(model_id=_MODELO, timeout_seconds=9)

    assert llm.model_id == _MODELO
    assert creados and creados[0][0] == "bedrock-runtime"


def test_no_loguea_el_prompt_ni_la_respuesta(caplog: pytest.LogCaptureFixture) -> None:
    """Logs de operación sin PII: ni el prompt del usuario ni la respuesta del modelo."""
    with caplog.at_level("INFO"):
        BedrockLLM(model_id=_MODELO, client=_DobleConverse()).invoke(messages=_mensajes())

    textos = [record.getMessage() for record in caplog.records]
    assert any("bedrock.converse.ok" in text for text in textos)
    for texto in textos:
        assert "¿Abierto hoy?" not in texto
        assert "Hola, ¿en qué te ayudo?" not in texto


def test_falla_al_construir_si_boto_no_encuentra_region(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin región configurada el error aparece al crear el adapter, no al invocar.

    Se comporta como el resto de la composición de dependencias: falla temprano y con el
    mensaje propio de botocore (configuración del proceso, no error del servicio).
    """

    def _client_sin_region(servicio: str, *, config: Any) -> _DobleConverse:
        raise NoRegionError()

    monkeypatch.setattr(llm_module.boto3, "client", _client_sin_region)
    with pytest.raises(NoRegionError):
        BedrockLLM(model_id=_MODELO)


def test_converse_client_es_un_protocolo() -> None:
    """`ConverseClient` es verificable en runtime para dobles y clientes reales."""
    assert isinstance(_DobleConverse(), ConverseClient)
