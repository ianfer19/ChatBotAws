"""Ports de salida del dominio de pedidos (Protocol): la implementación va en infrastructure/.

Mismo criterio que en `appointments`: el dominio declara qué persiste y qué consulta,
sin saber si debajo hay DynamoDB o Aurora, y todos los métodos reciben `tenant_id`
explícito para que el filtro por comercio nunca dependa del contenido del registro.
"""

from typing import Protocol, runtime_checkable

from .entities import Order


@runtime_checkable
class OrderRepositoryPort(Protocol):
    """Persistencia y consulta de pedidos, siempre limitadas a un comercio."""

    def save(self, *, tenant_id: str, order: Order) -> None:
        """Guarda el pedido, reemplazando el anterior si reutiliza su `id`.

        Args:
            tenant_id: Comercio bajo el que se guarda; debe coincidir con el del pedido.
            order: Pedido a persistir (modelo inmutable ya validado).

        Raises:
            ValidationError: Si `tenant_id` está vacío o no coincide con el del pedido.
        """
        ...

    def find(self, *, tenant_id: str, order_id: str) -> Order | None:
        """Busca un pedido por su identificador dentro del comercio indicado.

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            order_id: Identificador del pedido.

        Returns:
            El pedido si existe y pertenece a `tenant_id`; `None` en cualquier otro
            caso (un pedido ajeno se reporta como inexistente, nunca como ajeno).

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> Order | None:
        """Recupera el pedido creado por una petición anterior (idempotencia).

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            correlation_id: `correlation_id` de la creación original.

        Returns:
            El pedido ya creado para esa petición o `None` si no existe.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...
