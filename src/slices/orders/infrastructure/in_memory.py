"""Repositorio de pedidos en memoria: doble de tests y desarrollo previo a la infraestructura.

Mismo papel que `appointments/infrastructure/in_memory.py`: probar el dominio y las
tools sin tocar DynamoDB (ROADMAP §2.4). El aislamiento por tenant vive en la clave
del diccionario `(tenant_id, id)`.
"""

from shared.errors import ValidationError
from slices.orders.domain.entities import Order


def _require_tenant(tenant_id: str) -> None:
    """Rechaza operaciones sin comercio: ningún método trabaja "a ciegas".

    Args:
        tenant_id: Comercio resuelto en el gateway.

    Raises:
        ValidationError: Si `tenant_id` está vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en el repositorio de pedidos")


class InMemoryOrderRepository:
    """`OrderRepositoryPort` sobre un diccionario de proceso único.

    Example:
        >>> repo = InMemoryOrderRepository()
        >>> repo.find(tenant_id="Sede_Elite_01", order_id="o-1") is None
        True
    """

    def __init__(self) -> None:
        self._orders: dict[tuple[str, str], Order] = {}

    @staticmethod
    def _key(tenant_id: str, order_id: str) -> tuple[str, str]:
        """Clave canónica de almacenamiento: separa los comercios desde el origen.

        Args:
            tenant_id: Comercio dueño del pedido.
            order_id: Identificador del pedido.

        Returns:
            Tupla `(tenant_id, order_id)` usada como clave.
        """
        return (tenant_id, order_id)

    def save(self, *, tenant_id: str, order: Order) -> None:
        """Guarda el pedido bajo el tenant indicado (sobrescribe si ya existía).

        Args:
            tenant_id: Comercio bajo el que se guarda.
            order: Pedido a persistir.

        Raises:
            ValidationError: Si `tenant_id` está vacío o difiere del del pedido.
        """
        _require_tenant(tenant_id)
        if order.tenant_id != tenant_id:
            raise ValidationError(
                "el pedido pertenece a otro comercio",
                details={"tenant_solicitado": tenant_id, "tenant_pedido": order.tenant_id},
            )
        self._orders[self._key(tenant_id, order.id)] = order

    def find(self, *, tenant_id: str, order_id: str) -> Order | None:
        """Devuelve el pedido del tenant indicado o `None` si no existe.

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            order_id: Identificador del pedido.

        Returns:
            El pedido o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return self._orders.get(self._key(tenant_id, order_id))

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> Order | None:
        """Devuelve el pedido creado por esa petición (idempotencia) o `None`.

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            correlation_id: Clave de idempotencia de la creación.

        Returns:
            El pedido o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        for (stored_tenant, _), order in self._orders.items():
            if stored_tenant == tenant_id and order.correlation_id == correlation_id:
                return order
        return None
