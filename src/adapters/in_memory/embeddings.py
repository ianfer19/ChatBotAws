"""Doble en memoria de `EmbeddingsPort`: vectorización determinista sin Bedrock (Paso 7).

Bolsa de palabras con hash estable en 128 dimensiones: textos con las mismas
palabras quedan cerca (coseno alto) y textos sin palabras en común, lejos — lo
suficiente para probar umbral, deduplicación y aislamiento en tests y en el REPL
sin llamar a Bedrock. No es un modelo real: la ingesta y la consulta de
producción usan `adapters/bedrock/embeddings`.
"""

import re
from collections.abc import Sequence

_DIMENSIONES = 128
_PALABRA_RE = re.compile(r"[a-z0-9]+")


class InMemoryEmbeddings:
    """Vectorizador de prueba, determinista y sin red.

    Example:
        >>> emb = InMemoryEmbeddings()
        >>> emb.dimensions
        128
        >>> emb.embed(texts=["horario de apertura"])[0] == emb.embed(
        ...     texts=["horario de apertura"]
        ... )[0]
        True
    """

    @property
    def dimensions(self) -> int:
        """Dimensionalidad fija del doble (128)."""
        return _DIMENSIONES

    def embed(self, *, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Vectoriza por bolsa de palabras con hash estable por bucket.

        Args:
            texts: Textos a embeber (no vacíos, como exige el port).

        Returns:
            Un vector normalizado por texto, en el mismo orden.
        """
        return [self._vector(texto) for texto in texts]

    def _vector(self, texto: str) -> list[float]:
        """Cuenta las palabras del texto en buckets hasheados y normaliza.

        Args:
            texto: Texto a vectorizar.

        Returns:
            Vector L2-normalizado de `_DIMENSIONES` componentes (cero si no
            contiene palabras, en cuyo caso cualquier coseno da 0).
        """
        vector = [0.0] * _DIMENSIONES
        for palabra in _PALABRA_RE.findall(texto.lower()):
            bucket = _bucket(palabra)
            vector[bucket] += 1.0
        norma = sum(valor * valor for valor in vector) ** 0.5
        if norma == 0.0:
            return vector
        return [valor / norma for valor in vector]


def _bucket(palabra: str) -> int:
    """Hashea una palabra a su bucket (FNV-1a simple, determinista en todas las plataformas).

    Args:
        palabra: Palabra ya saneada (minúsculas y solo alfanuméricos).

    Returns:
        Índice en 0.._DIMENSIONES-1.
    """
    hash_ = 2166136261
    for byte in palabra.encode("utf-8"):
        hash_ ^= byte
        hash_ = (hash_ * 16777619) & 0xFFFFFFFF
    return hash_ % _DIMENSIONES
