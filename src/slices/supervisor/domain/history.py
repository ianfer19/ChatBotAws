"""Ventana de historial y resumen de los turnos desbordados (ROADMAP Paso 8).

Regla de negocio pura: el historial que ve el clasificador tiene tamaño máximo;
lo que sobra no se descarta en seco sino que se reduce a un resumen de un párrafo
que viaja como mensaje sintético al frente de la ventana. La llamada al LLM la
hace el nodo `application/nodes/window_history.py`; aquí solo viven las reglas
(sin AWS, sin langgraph, sin red).
"""

from collections.abc import Sequence

from shared.errors import ValidationError
from shared.ports import LLMMessage

RESUMEN_PREFIJO = "[Resumen de turnos anteriores] "


def split_window(
    historial: Sequence[LLMMessage], *, size: int
) -> tuple[list[LLMMessage], list[LLMMessage]]:
    """Parte el historial en la ventana que se conserva y los turnos que desbordan.

    Args:
        historial: Mensajes en orden cronológico (el más antiguo primero).
        size: Tamaño máximo de la ventana en mensajes.

    Returns:
        Tupla `(conservados, desbordados)`: los últimos `size` mensajes y los
        anteriores, ambos en orden cronológico. Si el historial ya cabe en la
        ventana, `desbordados` viene vacío.

    Raises:
        ValidationError: Si `size` es menor que 1.
    """
    if size < 1:
        raise ValidationError(
            "el tamaño de la ventana de historial debe ser al menos 1",
            details={"size": str(size)},
        )
    if len(historial) <= size:
        return list(historial), []
    return list(historial[-size:]), list(historial[:-size])


def summary_message(texto: str) -> LLMMessage:
    """Construye el mensaje sintético que lleva el resumen al frente de la ventana.

    Args:
        texto: Resumen ya redactado por el modelo (no vacío).

    Returns:
        Mensaje con el prefijo de resumen; rol `assistant` porque `LLMMessage`
        no admite `system` y el resumen lo produjo el modelo.
    """
    return LLMMessage(role="assistant", content=f"{RESUMEN_PREFIJO}{texto}")


def is_summary(mensaje: LLMMessage) -> bool:
    """Indica si un mensaje es el sintético de resumen (y no texto de cliente).

    Args:
        mensaje: Mensaje de la ventana.

    Returns:
        `True` si lleva el prefijo de resumen.
    """
    return mensaje.content.startswith(RESUMEN_PREFIJO)


def without_summary(historial: Sequence[LLMMessage]) -> list[LLMMessage]:
    """Quita de la ventana los mensajes sintéticos de resumen.

    El nodo la usa antes de re-resumir: así el resumen previo no se resume a sí
    mismo y nunca se anidan resúmenes.

    Args:
        historial: Ventana actual (con o sin resumen al frente).

    Returns:
        Solo los mensajes que no son resumen, en orden cronológico.
    """
    return [mensaje for mensaje in historial if not is_summary(mensaje)]
