"""Vectorización de textos tras un port (Paso 7: ingesta y consulta del RAG).

El **mismo** modelo embebe los chunks al indexar y la pregunta al buscar: si
divergen, la similitud es ruido. El adapter concreto es
`adapters/bedrock/embeddings` (modelo y dimensionalidad en `Settings`,
`TODO(verify)`; DATA_MODEL fija hoy `vector(1536)`).

El dominio y la aplicación ven solo este `Protocol`, nunca `boto3`.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsPort(Protocol):
    """Embedding de textos tras un port intercambiable."""

    @property
    def dimensions(self) -> int:
        """Dimensionalidad de los vectores devueltos.

        Returns:
            Número de componentes de cada embedding; debe coincidir con la
            definición de la columna pgvector (DATA_MODEL).
        """
        ...

    def embed(self, *, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Vectoriza los textos con el mismo modelo usado en la ingesta.

        Args:
            texts: Textos a embeber; al menos uno y sin vacíos (los valida el
                caller antes de llamar).

        Returns:
            Un vector por texto, en el mismo orden, con `dimensions` componentes.

        Raises:
            ToolError: Si el proveedor falla (red, 5xx o respuesta ilegible);
                lo traduce el adapter, nunca se fuga `botocore.ClientError`.
            ToolTimeoutError: Si la llamada excede el timeout configurado.
        """
        ...
