"""Abstracción del modelo de lenguaje con firma al estilo Converse (ADR 0004, Pasos 1-2).

LangGraph y los casos de uso hablan con `LLMPort`; el único adaptador es
`adapters/bedrock` (Converse API de Bedrock). Cambiar de modelo = cambiar
`BEDROCK_MODEL_ID`, nunca el código de los agentes.

Los tipos de este módulo imitan el vocabulario de Converse (roles `user`/`assistant`,
mensajes con contenido, `system` aparte e `inferenceConfig`) sin exponer `boto3` ni
nombres de API de AWS: el adapter traduce en un solo sitio.
"""

from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    """Un turno de la conversación tal y como lo espera Converse.

    Modelo inmutable y sin campos extra: lo que no se valida aquí no viaja al modelo.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class LLMResult(BaseModel):
    """Salida de una invocación: texto ya redactado y metadatos de la ejecución.

    `stop_reason` es el motivo de parada devuelto por el proveedor (p. ej. fin natural
    o tope de tokens) tal cual, sin traducir: el llamador decide qué hacer con él.

    Args:
        text: Contenido de la respuesta (primer bloque de texto si hubo varios).
        stop_reason: Motivo de parada reportado por el modelo, o `None` si no aplica.
        input_tokens: Tokens de entrada consumidos, si el proveedor los reporta.
        output_tokens: Tokens de salida consumidos, si el proveedor los reporta.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    stop_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


@runtime_checkable
class LLMPort(Protocol):
    """Generación de texto tras un port intercambiable (LangGraph → LLMPort → Bedrock)."""

    def invoke(
        self,
        *,
        messages: Sequence[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Invoca al modelo con el historial completo del turno (firma tipo Converse).

        Args:
            messages: Historial en orden cronológico; el último mensaje es el turno
                actual. Debe contener al menos un `LLMMessage`.
            system: Instrucciones de sistema ya renderizadas (plantilla + contexto de
                tenant); el adapter las envía como bloque de sistema separado.
            max_tokens: Tope de salida; `None` deja que el adapter use el del modelo.
            temperature: Muestreo; `None` deja el valor por defecto del modelo.

        Returns:
            `LLMResult` con el texto de la respuesta y sus metadatos de ejecución.

        Raises:
            ToolError: Si el proveedor falla (red, 5xx o respuesta ilegible); lo traduce
                el adapter, nunca se fuga `botocore.ClientError`.
            ToolTimeoutError: Si la invocación excede el timeout configurado.
        """
        ...
