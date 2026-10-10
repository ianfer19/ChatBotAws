"""Adapter de embeddings de Amazon Bedrock sobre `InvokeModel` (Paso 7: RAG).

`BedrockEmbeddings` implementa `shared.ports.EmbeddingsPort`: el **mismo** modelo
vectoriza los chunks al ingerir y la pregunta al buscar. La API se verificó con
una invocación real contra la cuenta de desarrollo:

- operación: `invoke_model(modelId=..., body=..., contentType=..., accept=...)`
  del cliente `bedrock-runtime`;
- cuerpo de Titan Embeddings v1: ``{"inputText": "..."}`` (un texto por llamada);
- respuesta: ``{"embedding": [...], "inputTextTokenCount": n}`` con **1536**
  dimensiones, que es exactamente `vector(1536)` de DATA_MODEL.

`TODO(verify)`: batching (¿admite el modelo varios textos por llamada?), precio
(Paso 14) y qué modelo usar si se cambia de familia (el cuerpo de cada
proveedor difiere).
"""

import json
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

_logger = get_logger(__name__)

_BEDROCK_SERVICE = "bedrock-runtime"
_JSON = "application/json"


@runtime_checkable
class InvokeModelClient(Protocol):
    """Subconjunto de `bedrock-runtime` que usa este adapter (DI y dobles de test)."""

    def invoke_model(
        self,
        *,
        modelId: str,
        body: bytes,
        contentType: str,
        accept: str,
    ) -> dict[str, Any]:
        """Invoca al modelo de embeddings con `InvokeModel`.

        Args:
            modelId: Modelo de embeddings (p. ej. `amazon.titan-embed-text-v1`).
            body: Cuerpo JSON del proveedor (`{"inputText": ...}` para Titan).
            contentType: Tipo del cuerpo (JSON).
            accept: Tipo esperado de la respuesta (JSON).

        Returns:
            Diccionario con `body` (stream legible) y `contentType`.

        Raises:
            ClientError: Si el servicio devuelve un error de negocio.
            BotoCoreError: Si falla la red, el timeout o la región.
        """
        ...


def _default_client(timeout_seconds: int) -> InvokeModelClient:
    """Crea el cliente `bedrock-runtime` con timeout y reintentos limitados.

    Args:
        timeout_seconds: Segundos de espera de conexión y de lectura.

    Returns:
        Cliente listo para llamar a `invoke_model`.

    TODO(verify): mismo patrón que `llm.py` (`connect_timeout`, `read_timeout`,
    `retries.mode`), verificado contra la doc de botocore en el Paso 2.
    """
    config = Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    # boto3 no tiene stubs: la anotación es la que garantiza la firma del Protocol.
    cliente: InvokeModelClient = boto3.client(_BEDROCK_SERVICE, config=config)
    return cliente


class BedrockEmbeddings:
    """`EmbeddingsPort` sobre `InvokeModel` de Amazon Bedrock.

    El cliente se inyecta por constructor (regla de `adapters/AGENTS.md` nº 1);
    si no llega, se crea aquí mismo, nunca a nivel de módulo.

    Example:
        >>> emb = BedrockEmbeddings(model_id="amazon.titan-embed-text-v1")
        >>> emb.dimensions
        1536
    """

    def __init__(
        self,
        *,
        model_id: str,
        dimensions: int = 1536,
        timeout_seconds: int = 30,
        client: InvokeModelClient | None = None,
    ) -> None:
        """Prepara el adapter con su modelo, dimensionalidad, timeout y cliente.

        Args:
            model_id: Modelo de embeddings (`CHATBOT_BEDROCK_EMBEDDINGS_MODEL_ID`).
            dimensions: Componentes esperados del vector; debe coincidir con la
                columna pgvector (`CHATBOT_BEDROCK_EMBEDDINGS_DIMENSIONS`).
            timeout_seconds: Segundos de espera por llamada.
            client: Cliente `invoke_model` a inyectar; si es `None` el real.

        Raises:
            ValidationError: Si falta `model_id`, `dimensions` no es positiva o
                el timeout no es positivo.
        """
        if not model_id:
            raise ValidationError(
                "model_id vacío: define CHATBOT_BEDROCK_EMBEDDINGS_MODEL_ID",
                details={"setting": "bedrock_embeddings_model_id"},
            )
        if dimensions < 1:
            raise ValidationError(
                "dimensionalidad de embeddings inválida",
                details={"dimensions": str(dimensions)},
            )
        if timeout_seconds < 1:
            raise ValidationError(
                "timeout inválido para Bedrock",
                details={"timeout_seconds": str(timeout_seconds)},
            )
        self._model_id = model_id
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds
        self._client = client if client is not None else _default_client(timeout_seconds)

    @property
    def dimensions(self) -> int:
        """Componentes del vector (la misma dimensión que la columna pgvector)."""
        return self._dimensions

    def embed(self, *, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Vectoriza los textos, uno por invocación (Titan no admite lote).

        Args:
            texts: Textos a embeber; al menos uno y ninguno vacío.

        Returns:
            Un vector de `dimensions` componentes por texto, en el mismo orden.

        Raises:
            ValidationError: Si `texts` está vacío o contiene un texto vacío.
            ToolError: Si Bedrock devuelve un error, si la respuesta tiene una
                forma inesperada o si la dimensionalidad no coincide con la
                columna pgvector.
            ToolTimeoutError: Si la llamada excede el timeout configurado.
        """
        if not texts:
            raise ValidationError("texts vacío: nada que vectorizar")
        vectores = [self._invoke(texto) for texto in texts]
        _logger.info(
            "bedrock.embed.ok",
            extra={
                "model_id": self._model_id,
                "texts": len(texts),
                "dimensions": self._dimensions,
            },
        )
        return vectores

    def _invoke(self, texto: str) -> list[float]:
        """Invoca al modelo con un solo texto y devuelve su embedding validado.

        Args:
            texto: Texto a vectorizar (no vacío; lo valida el caller).

        Returns:
            Vector de `dimensions` componentes como `list[float]`.

        Raises:
            ToolError: Si Bedrock falla o responde con una forma inesperada.
            ToolTimeoutError: Si la llamada excede el timeout.
        """
        if not texto.strip():
            raise ValidationError("texto vacío: nada que vectorizar")
        cuerpo = json.dumps({"inputText": texto}).encode("utf-8")
        try:
            respuesta = self._client.invoke_model(
                modelId=self._model_id,
                body=cuerpo,
                contentType=_JSON,
                accept=_JSON,
            )
            payload = json.loads(respuesta["body"].read())
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", "unknown"))
            _logger.error(
                "bedrock.embed.error",
                extra={"model_id": self._model_id, "error_code": error_code},
            )
            raise ToolError(
                "Bedrock InvokeModel devolvió un error",
                details={"model_id": self._model_id, "error_code": error_code},
            ) from exc
        except (ReadTimeoutError, ConnectTimeoutError) as exc:
            _logger.error(
                "bedrock.embed.timeout",
                extra={"model_id": self._model_id, "timeout_seconds": self._timeout_seconds},
            )
            raise ToolTimeoutError(
                "Bedrock InvokeModel excedió el timeout",
                details={
                    "model_id": self._model_id,
                    "timeout_seconds": str(self._timeout_seconds),
                },
            ) from exc
        except BotoCoreError as exc:
            _logger.error(
                "bedrock.embed.client_error",
                extra={"model_id": self._model_id, "error": type(exc).__name__},
            )
            raise ToolError(
                "no se pudo contactar con Bedrock para embeddings",
                details={"model_id": self._model_id, "error": type(exc).__name__},
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            _logger.error(
                "bedrock.embed.malformed",
                extra={"model_id": self._model_id},
            )
            raise ToolError(
                "respuesta de Bedrock con forma inesperada",
                details={"model_id": self._model_id},
            ) from exc
        return self._to_vector(payload)

    def _to_vector(self, payload: object) -> list[float]:
        """Extrae y valida el embedding de la respuesta del modelo.

        Args:
            payload: Cuerpo JSON ya parseado de la respuesta.

        Returns:
            Vector de `dimensions` componentes.

        Raises:
            ToolError: Si falta `embedding`, si no es una lista numérica o si
                su tamaño no coincide con la columna pgvector (defensa contra
                un modelo configurado mal: el esquema no podría recibirlo).
        """
        embedding = payload.get("embedding") if isinstance(payload, dict) else None
        if not isinstance(embedding, list) or not embedding:
            raise ToolError(
                "respuesta de Bedrock sin embedding",
                details={"model_id": self._model_id},
            )
        try:
            vector = [float(valor) for valor in embedding]
        except (TypeError, ValueError) as exc:
            raise ToolError(
                "embedding de Bedrock con valores no numéricos",
                details={"model_id": self._model_id},
            ) from exc
        if len(vector) != self._dimensions:
            raise ToolError(
                "dimensionalidad del embedding distinta de la columna pgvector",
                details={
                    "model_id": self._model_id,
                    "esperado": str(self._dimensions),
                    "recibido": str(len(vector)),
                },
            )
        return vector
