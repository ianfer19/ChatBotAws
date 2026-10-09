"""Dobles en memoria de pedidos: repositorio, catálogo y legacy (previo a la infraestructura).

Mismo papel que `appointments/infrastructure/in_memory.py`: probar el dominio y las
tools sin tocar DynamoDB ni HTTP (ROADMAP §2.4). El aislamiento por tenant vive en la
clave del diccionario `(tenant_id, id)`. `InMemoryLegacyOrders` simula el backend
creando pedidos idempotentes por `correlation_id` con estado canónico `ABIERTA`;
`InMemoryCatalog` es un catálogo sintético con precios fijos que jamás sale del LLM.
"""

import uuid
from collections.abc import Sequence

from shared.errors import ValidationError
from shared.ports import ClockPort
from slices.orders.domain.entities import Order, OrderItem, Product
from slices.orders.domain.errors import OrderNotFound
from slices.orders.domain.ports import OrderRepositoryPort


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

    def list_for_tenant(self, *, tenant_id: str) -> list[Order]:
        """Devuelve todos los pedidos guardados de un comercio (para tests y auditoría).

        Args:
            tenant_id: Comercio cuyos pedidos se listan.

        Returns:
            Los pedidos persistidos de `tenant_id`, en orden de inserción.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return [
            order
            for (stored_tenant, _), order in self._orders.items()
            if stored_tenant == tenant_id
        ]

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


class InMemoryLegacyOrders:
    """`LegacyOrdersPort` sobre un repositorio en memoria (doble del backend).

    Reproduce el contrato mínimo que usan las tools: creación idempotente por
    `correlation_id`, consulta de estado y anulación dentro de la ventana de deshacer
    (doble de `void_order`; `TODO(verify)` contra el endpoint real, Paso 11).

    Example:
        >>> from datetime import datetime
        >>> class _Reloj:
        ...     def now(self) -> datetime:
        ...         return datetime(2026, 3, 2, 12, 0)
        >>> legacy = InMemoryLegacyOrders(InMemoryOrderRepository(), clock=_Reloj())
        >>> pedido = legacy.create_order(
        ...     tenant_id="Sede_Elite_01",
        ...     correlation_id="corr-1",
        ...     items=(OrderItem(sku="A-100", quantity=1),),
        ...     total=15_000,
        ... )
        >>> pedido.status
        'ABIERTA'
    """

    def __init__(self, store: OrderRepositoryPort, *, clock: ClockPort) -> None:
        """Guarda el repositorio de persistencia y el reloj del backend simulado.

        Args:
            store: Repositorio donde se materializan los pedidos creados/anulados.
            clock: Reloj para fijar `created_at` (simula el instante del backend).
        """
        self._store = store
        self._clock = clock

    def create_order(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        items: Sequence[OrderItem],
        total: float,
    ) -> Order:
        """Crea el pedido (o devuelve el ya creado para esa petición).

        Args:
            tenant_id: Comercio dueño del pedido.
            correlation_id: Clave de idempotencia.
            items: Líneas del pedido.
            total: Monto total calculado por el código.

        Returns:
            El pedido registrado (idempotente: repetir no duplica).

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        previa = self._store.find_by_correlation_id(
            tenant_id=tenant_id, correlation_id=correlation_id
        )
        if previa is not None:
            return previa
        pedido = Order(
            id=f"ord-{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            items=tuple(items),
            status="ABIERTA",
            created_at=self._clock.now(),
            total=total,
            correlation_id=correlation_id,
        )
        self._store.save(tenant_id=tenant_id, order=pedido)
        return pedido

    def get_order_status(self, *, tenant_id: str, order_id: str) -> Order | None:
        """Consulta el estado de un pedido del comercio.

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            order_id: Identificador del pedido.

        Returns:
            El pedido o `None` si no existe o es ajeno.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return self._store.find(tenant_id=tenant_id, order_id=order_id)

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> Order | None:
        """Recupera el pedido de esa petición (idempotencia) o `None`.

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            correlation_id: Clave de idempotencia de la creación.

        Returns:
            El pedido o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return self._store.find_by_correlation_id(
            tenant_id=tenant_id, correlation_id=correlation_id
        )

    def void_order(self, *, tenant_id: str, order_id: str) -> Order:
        """Anula un pedido abierto (doble de la anulación del backend).

        Args:
            tenant_id: Comercio dueño del pedido.
            order_id: Pedido a anular.

        Returns:
            El pedido con estado `ANULADA`.

        Raises:
            ValidationError: Si falta `tenant_id`.
            OrderNotFound: Si el pedido no existe en este comercio.
        """
        _require_tenant(tenant_id)
        pedido = self._store.find(tenant_id=tenant_id, order_id=order_id)
        if pedido is None:
            raise OrderNotFound("pedido no encontrado para anular", details={"order_id": order_id})
        anulado = pedido.model_copy(update={"status": "ANULADA"})
        self._store.save(tenant_id=tenant_id, order=anulado)
        return anulado


class InMemoryCatalog:
    """`CatalogPort` con productos fijos en memoria (precios sintéticos de test).

    Example:
        >>> catalogo = InMemoryCatalog(
        ...     [
        ...         Product(
        ...             tenant_id="Sede_Elite_01",
        ...             sku="A-100",
        ...             name="Alitas BBQ",
        ...             price=18_000,
        ...             category="entradas",
        ...         )
        ...     ]
        ... )
        >>> catalogo.find_by_sku(tenant_id="Sede_Elite_01", sku="A-100").price
        18000.0
    """

    def __init__(self, products: Sequence[Product] = ()) -> None:
        """Indexa los productos por `(tenant_id, sku)`.

        Args:
            products: Productos de todos los comercios de prueba.
        """
        self._products = {(producto.tenant_id, producto.sku): producto for producto in products}

    def search(self, *, tenant_id: str, query: str) -> list[Product]:
        """Busca por nombre o SKU dentro del comercio (subcadena, case-insensitive).

        Args:
            tenant_id: Comercio cuyo catálogo se consulta.
            query: Término de búsqueda.

        Returns:
            Productos coincidentes, con su precio real del catálogo.

        Raises:
            ValidationError: Si falta `tenant_id` o `query`.
        """
        _require_tenant(tenant_id)
        if not query:
            raise ValidationError("query vacía en la búsqueda de productos")
        termino = query.casefold()
        return [
            producto
            for (_, sku), producto in self._products.items()
            if producto.tenant_id == tenant_id
            and (termino in producto.name.casefold() or termino in sku.casefold())
        ]

    def list_menu(self, *, tenant_id: str, category: str | None = None) -> list[Product]:
        """Lista el menú del comercio (opcionalmente de una categoría).

        Args:
            tenant_id: Comercio cuyo catálogo se consulta.
            category: Categoría a filtrar (`None` = todo el menú).

        Returns:
            Productos del menú en orden de inserción.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return [
            producto
            for (_, _), producto in self._products.items()
            if producto.tenant_id == tenant_id
            and (category is None or producto.category == category)
        ]

    def find_by_sku(self, *, tenant_id: str, sku: str) -> Product | None:
        """Busca un producto por SKU dentro del comercio.

        Args:
            tenant_id: Comercio cuyo catálogo se consulta.
            sku: Identificador del producto.

        Returns:
            El producto o `None` si no existe o es ajeno.

        Raises:
            ValidationError: Si falta `tenant_id` o `sku`.
        """
        _require_tenant(tenant_id)
        if not sku:
            raise ValidationError("sku vacío en find_by_sku")
        return self._products.get((tenant_id, sku))
