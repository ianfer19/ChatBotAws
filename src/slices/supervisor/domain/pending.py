"""Respuesta del cliente a un draft pendiente: clasificación determinista (ADR 0011.5).

El router `resolve_pending` decide sin LLM cuando la respuesta es exacta («sí», «no»,
«cancelar»): son conjuntos cerrados de palabras, normalizadas (minúsculas, sin acentos
ni signos) para que «Sí.» o «SI» cuenten igual. Cualquier otra cosa no es una
respuesta de confirmación y pasa al clasificador normal (o al LLM de respaldo del nodo,
solo cuando hay un draft `AWAITING_CONFIRMATION`).

La plantilla de respuesta es deliberadamente genérica: el router no conoce el detalle
del pedido ni de la cita (eso vive en el especialista), solo el resultado de la
operación.
"""

import re
import unicodedata
from typing import Literal

RESPUESTAS_AFIRMATIVAS: frozenset[str] = frozenset(
    {"si", "s", "yes", "ok", "confirmo", "confirmar", "dale", "de acuerdo"}
)
"""Respuestas exactas que confirman un draft a la espera (se interpreta como `affirm`)."""

RESPUESTAS_NEGATIVAS: frozenset[str] = frozenset(
    {"no", "n", "nope", "nah", "cancelar", "cancelo", "mejor no", "no gracias"}
)
"""Respuestas exactas que rechazan un draft a la espera (se interpreta como `deny`)."""

RESPUESTAS_DESHACER: frozenset[str] = frozenset(
    {"cancelar", "cancelo", "deshacer", "deshacerlo", "anular", "anula"}
)
"""Respuestas exactas que anulan un pedido/cita ya commiteado dentro de su ventana."""

_RESOLUCIONES = Literal["affirmed", "denied", "undoed"]

_PLANTILLAS: dict[str, str] = {
    "affirmed": "Listo, confirmado: ya quedó registrado. ¿En qué más te ayudo?",
    "denied": "Perfecto, no hice nada. Si lo quieres retomar, pídemelo de nuevo.",
    "undoed": "Hecho: lo deshice y quedó anulado. ¿En qué más te ayudo?",
}


def normalizar(texto: str) -> str:
    """Normaliza una respuesta para compararla contra los conjuntos exactos.

    Minúsculas, sin acentos, sin signos de puntuación y con los espacios colapsados:
    «Sí. » y «SI» resultan en `si`; «No, gracias» resultan en `no gracias`.

    Args:
        texto: Respuesta cruda del cliente.

    Returns:
        Texto normalizado listo para comparación exacta.
    """
    sin_acentos = "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto.lower().strip())
        if not unicodedata.combining(caracter)
    )
    sin_signos = re.sub(r"[^\w\s]", " ", sin_acentos)
    return re.sub(r"\s+", " ", sin_signos).strip()


def es_afirmativa(texto: str) -> bool:
    """Indica si la respuesta confirma exactamente un draft a la espera.

    Args:
        texto: Respuesta cruda del cliente.

    Returns:
        `True` si normalizada coincide con `RESPUESTAS_AFIRMATIVAS`.
    """
    return normalizar(texto) in RESPUESTAS_AFIRMATIVAS


def es_negativa(texto: str) -> bool:
    """Indica si la respuesta rechaza exactamente un draft a la espera.

    Args:
        texto: Respuesta cruda del cliente.

    Returns:
        `True` si normalizada coincide con `RESPUESTAS_NEGATIVAS`.
    """
    return normalizar(texto) in RESPUESTAS_NEGATIVAS


def es_de_deshacer(texto: str) -> bool:
    """Indica si la respuesta pide deshacer exactamente un draft ya commiteado.

    Args:
        texto: Respuesta cruda del cliente.

    Returns:
        `True` si normalizada coincide con `RESPUESTAS_DESHACER`.
    """
    return normalizar(texto) in RESPUESTAS_DESHACER


def respuesta_plantilla(resolucion: _RESOLUCIONES) -> str:
    """Devuelve la respuesta fija del router para una resolución de draft.

    Args:
        resolucion: Resultado de la operación (`affirmed`, `denied` u `undoed`).

    Returns:
        Mensaje genérico sin detalle del pedido ni de la cita.
    """
    return _PLANTILLAS[resolucion]
