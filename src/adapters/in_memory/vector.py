"""Doble en memoria de `VectorStorePort`: aislamiento por tenant sin Aurora (Paso 7).

Mismo patrón que `InMemoryDraftStore`: implementa el port tal cual para que los
tests y el REPL prueben la lógica del slice sin servicios externos. La búsqueda
ordena por similitud coseno y **solo** mira los registros del `tenant_id`
pedido — el aislamiento se prueba aquí igual que en el adapter real.
"""

import math
from collections.abc import Sequence

from shared.errors import ValidationError
from shared.ports.vector import VectorHit, VectorRecord


class InMemoryVectorStore:
    """Almacén vectorial en memoria, aislado por `(tenant_id, id)`.

    Example:
        >>> from shared.ports.vector import VectorRecord
        >>> store = InMemoryVectorStore()
        >>> store.upsert(records=[
        ...     VectorRecord(
        ...         id="c1",
        ...         tenant_id="Sede_Elite_01",
        ...         text="abrimos de lunes a sabado",
        ...         vector=[1.0, 0.0],
        ...     )
        ... ])
        >>> [hit.text for hit in store.search(
        ...     vector=[1.0, 0.0], tenant_id="Sede_Elite_01"
        ... )]
        ['abrimos de lunes a sabado']
    """

    def __init__(self) -> None:
        """Crea el almacén vacío (un dict por clave compuesta de tenant e id)."""
        self._records: dict[tuple[str, str], VectorRecord] = {}

    def upsert(self, *, records: Sequence[VectorRecord]) -> None:
        """Indexa o reemplaza registros del mismo tenant (idempotente por id).

        Args:
            records: Registros con su embedding ya calculado.

        Raises:
            ValidationError: Si algún registro no trae tenant.
        """
        for record in records:
            if not record.tenant_id:
                raise ValidationError("registro vectorial sin tenant_id")
            self._records[(record.tenant_id, record.id)] = record

    def search(
        self, *, vector: Sequence[float], tenant_id: str, limit: int = 5
    ) -> Sequence[VectorHit]:
        """Vecinos más parecidos **solo del tenant pedido**, por similitud coseno.

        Args:
            vector: Embedding de la consulta.
            tenant_id: Comercio cuyo conocimiento se consulta; obligatorio.
            limit: Máximo de resultados (recortado a los primeros ordenados).

        Returns:
            Hits con score en 0..1, de mayor a menor similitud.

        Raises:
            ValidationError: Si `tenant_id` está vacío.
        """
        if not tenant_id:
            raise ValidationError("búsqueda vectorial sin tenant_id")
        candidatos = [record for (owner, _), record in self._records.items() if owner == tenant_id]
        puntuados = sorted(
            ((_cosine(vector, record.vector), record) for record in candidatos),
            key=lambda par: par[0],
            reverse=True,
        )
        return [
            VectorHit(
                id=record.id,
                tenant_id=record.tenant_id,
                text=record.text,
                score=max(0.0, min(1.0, score)),
                metadata=record.metadata,
            )
            for score, record in puntuados[: max(limit, 0)]
        ]

    def delete(self, *, tenant_id: str, ids: Sequence[str]) -> None:
        """Borra registros del tenant indicado; los ids ajenos se ignoran.

        Args:
            tenant_id: Comercio dueño de los registros.
            ids: Identificadores a eliminar.

        Raises:
            ValidationError: Si `tenant_id` está vacío.
        """
        if not tenant_id:
            raise ValidationError("borrado vectorial sin tenant_id")
        for identificador in ids:
            self._records.pop((tenant_id, identificador), None)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Similitud coseno entre dos vectores (0 si alguno es vacío o de otra dimensión).

    Args:
        a: Primer vector.
        b: Segundo vector.

    Returns:
        Coseno recortado a 0..1 para el score del hit.
    """
    if len(a) != len(b) or not a:
        return 0.0
    producto = sum(x * y for x, y in zip(a, b, strict=True))
    norma_a = math.sqrt(sum(x * x for x in a))
    norma_b = math.sqrt(sum(y * y for y in b))
    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0
    return producto / (norma_a * norma_b)
