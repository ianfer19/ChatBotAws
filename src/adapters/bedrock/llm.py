"""Adapter de Amazon Bedrock sobre la Converse API (Paso 2).

`BedrockLLM` es la **única** pieza del sistema que habla con Bedrock: implementa
`shared.ports.LLMPort`, de modo que LangGraph y el dominio solo ven el port y el
`modelId` de `Settings.bedrock_model_id` decide qué modelo responde (ADR 0004).

Nombres de la API: los campos de la petición y de la respuesta (`modelId`,
`messages`, `system`, `inferenceConfig.maxTokens`, `stopReason`, `usage.inputTokens`)
se verificaron con la ayuda oficial de `aws bedrock-runtime converse` y con una
invocación real contra la cuenta de desarrollo (Paso 2).
`TODO(verify)`: versión mínima de `boto3` y precio por 1M de tokens (Paso 14).
"""

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

from shared.errors import ToolError, ToolTimeoutError, ValidationError
from shared.logging import get_logger
from shared.ports import LLMMessage, LLMResult

_logger = get_logger(__name__)

_BEDROCK_SERVICE = "bedrock-runtime"


@runtime_checkable
class ConverseClient(Protocol):
    """Subconjunto de `bedrock-runtime` que usa este adapter (DI y dobles de test)."""

    def converse(
        self,
        *,
        modelId: str,
        messages: list[dict[str, Any]],
        system: list[dict[str, Any]] | None = None,
        inferenceConfig: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoca al modelo y devuelve la respuesta de Converse.

        Args:
            modelId: Identificador del modelo o perfil de inferencia a usar.
            messages: Historial en el formato de Converse (`role` + `content[].text`).
            system: Bloque de instrucciones de sistema, si lo hay.
            inferenceConfig: Parámetros de muestreo (`maxTokens`, `temperature`...).

        Returns:
            Diccionario con `output`, `stopReason` y `usage`.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


def _default_client(timeout_seconds: int) -> ConverseClient:
    """Crea el cliente `bedrock-runtime` con timeout y reintentos limitados.

    Args:
        timeout_seconds: Segundos de espera de conexión y de lectura.

    Returns:
        Cliente listo para llamar a `converse`.

    TODO(verify): nombres exactos de `Config` (`connect_timeout`, `read_timeout`,
    `retries.mode`) y número de reintentos, verificados contra la doc de botocore.
    """
    config = Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    # boto3 no tiene stubs: la anotación es la que garantiza la firma de `ConverseClient`.
    cliente: ConverseClient = boto3.client(_BEDROCK_SERVICE, config=config)
    return cliente


def _to_converse_messages(messages: Sequence[LLMMessage]) -> list[dict[str, Any]]:
    """Traduce los mensajes del port al formato de Converse.

    Args:
        messages: Historial con roles `user`/`assistant`.

    Returns:
        Lista de mensajes con `content` como bloques de texto.
    """
    return [{"role": message.role, "content": [{"text": message.content}]} for message in messages]


def _to_result(response: dict[str, Any]) -> LLMResult:
    """Extrae texto, motivo de parada y tokens de la respuesta de Converse.

    Args:
        response: Respuesta completa devuelta por `converse`.

    Returns:
        `LLMResult` con el texto concatenado y los metadatos disponibles.

    Raises:
        ToolError: Si la respuesta no trae el formato esperado (no se fuga `KeyError`).
    """
    try:
        blocks = response["output"]["message"]["content"]
        usage = response["usage"]
        text = "".join(block["text"] for block in blocks if "text" in block)
        return LLMResult(
            text=text,
            stop_reason=response.get("stopReason"),
            input_tokens=usage.get("inputTokens"),
            output_tokens=usage.get("outputTokens"),
        )
    except (KeyError, TypeError) as exc:
        raise ToolError("respuesta de Bedrock con forma inesperada") from exc


class BedrockLLM:
    """`LLMPort` sobre la Converse API de Bedrock.

    El cliente se inyecta por constructor (regla de `adapters/AGENTS.md` nº 1); si no
    llega, se crea aquí mismo, nunca a nivel de módulo.

    Example:
        >>> BedrockLLM(model_id="modelo-de-prueba", client=falso_cliente).model_id
        'modelo-de-prueba'
    """

    def __init__(
        self,
        *,
        model_id: str,
        timeout_seconds: int = 30,
        client: ConverseClient | None = None,
    ) -> None:
        """Prepara el adapter con su modelo, timeout y cliente.

        Args:
            model_id: Modelo o perfil de inferencia de Bedrock (`CHATBOT_BEDROCK_MODEL_ID`).
            timeout_seconds: Segundos de espera por llamada.
            cliente: Cliente Converse a inyectar; si es `None` se crea el real.

        Raises:
            ValidationError: Si falta `model_id` o el timeout no es positivo.
        """
        if not model_id:
            raise ValidationError(
                "model_id vacío: define CHATBOT_BEDROCK_MODEL_ID",
                details={"setting": "bedrock_model_id"},
            )
        if timeout_seconds < 1:
            raise ValidationError(
                "timeout inválido para Bedrock",
                details={"timeout_seconds": str(timeout_seconds)},
            )
        self._model_id = model_id
        self._timeout_seconds = timeout_seconds
        self._client = client if client is not None else _default_client(timeout_seconds)

    @property
    def model_id(self) -> str:
        """Modelo configurado (para logs y diagnóstico; nunca el prompt)."""
        return self._model_id

    def invoke(
        self,
        *,
        messages: Sequence[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Invoca al modelo con la Converse API y devuelve su respuesta.

        Args:
            messages: Historial cronológico; el último mensaje es el turno actual.
            system: Instrucciones de sistema ya renderizadas.
            max_tokens: Tope de salida; `None` deja el valor por defecto del modelo.
            temperature: Muestreo; `None` deja el valor por defecto del modelo.

        Returns:
            `LLMResult` con la respuesta y sus metadatos de ejecución.

        Raises:
            ToolError: Si Bedrock devuelve un error, si la red falla o si la respuesta
                tiene una forma inesperada.
            ToolTimeoutError: Si la llamada excede el timeout configurado.
        """
        request: dict[str, Any] = {
            "modelId": self._model_id,
            "messages": _to_converse_messages(messages),
        }
        if system:
            request["system"] = [{"text": system}]
        inference_config = {
            key: value
            for key, value in (
                ("maxTokens", max_tokens),
                ("temperature", temperature),
            )
            if value is not None
        }
        if inference_config:
            request["inferenceConfig"] = inference_config

        try:
            response = self._client.converse(**request)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", "unknown"))
            _logger.error(
                "bedrock.converse.error",
                extra={"model_id": self._model_id, "error_code": error_code},
            )
            raise ToolError(
                "Bedrock Converse devolvió un error",
                details={"model_id": self._model_id, "error_code": error_code},
            ) from exc
        except (ReadTimeoutError, ConnectTimeoutError) as exc:
            _logger.error(
                "bedrock.converse.timeout",
                extra={"model_id": self._model_id, "timeout_seconds": self._timeout_seconds},
            )
            raise ToolTimeoutError(
                "Bedrock Converse excedió el timeout",
                details={"model_id": self._model_id, "timeout_seconds": str(self._timeout_seconds)},
            ) from exc
        except BotoCoreError as exc:
            _logger.error(
                "bedrock.converse.client_error",
                extra={"model_id": self._model_id, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudo contactar con Bedrock",
                details={"model_id": self._model_id, "error": type(exc).__name__},
            ) from exc

        resultado = _to_result(response)
        _logger.info(
            "bedrock.converse.ok",
            extra={
                "model_id": self._model_id,
                "stop_reason": resultado.stop_reason,
                "input_tokens": resultado.input_tokens,
                "output_tokens": resultado.output_tokens,
            },
        )
        return resultado
