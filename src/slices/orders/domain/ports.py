"""Ports de salida del dominio de pedidos (Protocol): la implementación va en infrastructure/.

Mismo criterio que en `appointments`: el dominio declara qué persiste, qué consulta y
qué pide al backend, sin saber si debajo hay DynamoDB, HTTP o dobles en memoria, y
todos los métodos reciben `tenant_id` explícito para que el filtro por comercio nunca
dependa del contenido del registro.

`LegacyOrdersPort` y `CatalogPort` (Paso 5) siguen sin HTTP: el adapter real llega en el
Paso 11 tras el AgentCore Gateway (`TODO(verify)` de los endpoints).
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .entities import Order, OrderItem, Product


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


@runtime_checkable
class CatalogPort(Protocol):
    """Lectura del catálogo de productos de un comercio (hoy dobles; RAG/legacy luego)."""

    def search(self, *, tenant_id: str, query: str) -> list[Product]:
        """Busca productos por nombre o descripción dentro del comercio.

        Args:
            tenant_id: Comercio cuyo catálogo se consulta.
            query: Término de búsqueda escrito por el cliente/LLM.

        Returns:
            Productos coincidentes (con precio y disponibilidad reales); lista vacía
            si no hay coincidencias.

        Raises:
            ValidationError: Si falta `tenant_id` o `query`.
        """
        ...

    def list_menu(self, *, tenant_id: str, category: str | None = None) -> list[Product]:
        """Lista el menú completo (o de una categoría) del comercio.

        Args:
            tenant_id: Comercio cuyo catálogo se consulta.
            category: Categoría opcional a filtrar.

        Returns:
            Productos del menú con precio y disponibilidad reales.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def find_by_sku(self, *, tenant_id: str, sku: str) -> Product | None:
        """Busca un producto por su SKU dentro del comercio.

        Args:
            tenant_id: Comercio cuyo catálogo se consulta.
            sku: Identificador del producto.

        Returns:
            El producto si existe en ese comercio; `None` si no existe o es ajeno
            (un producto ajeno se reporta como inexistente, nunca como ajeno).

        Raises:
            ValidationError: Si falta `tenant_id` o `sku`.
        """
        ...


@runtime_checkable
class LegacyOrdersPort(Protocol):
    """Operaciones de pedido contra el backend legacy (sin HTTP hasta el Paso 11)."""

    def create_order(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        items: Sequence[OrderItem],
        total: float,
    ) -> Order:
        """Crea el pedido en el backend (idempotente por `correlation_id`).

        Args:
            tenant_id: Comercio dueño del pedido.
            correlation_id: Idempotencia de la petición.
            items: Líneas del pedido (SKU y cantidad; precios ya calculados).
            total: Monto total calculado por el código desde el catálogo.

        Returns:
            El pedido registrado, con su `id` y estado canónico.

        Raises:
            LegacyTimeout: Si el backend no responde en el timeout.
            PaymentRejected: Si el backend rechaza el pago (nunca se reintenta).
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def get_order_status(self, *, tenant_id: str, order_id: str) -> Order | None:
        """Consulta el estado de un pedido dentro del comercio.

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            order_id: Identificador del pedido.

        Returns:
            El pedido si existe y pertenece a `tenant_id`; `None` en otro caso.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> Order | None:
        """Recupera el pedido de una petición anterior (idempotencia de creación).

        Args:
            tenant_id: Comercio cuyos pedidos se consultan.
            correlation_id: `correlation_id` de la creación original.

        Returns:
            El pedido ya creado para esa petición o `None` si no existe.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def void_order(self, *, tenant_id: str, order_id: str) -> Order:
        """Anula un pedido abierto (doble de la anulación del backend).

        Solo lo usan las ventanas de deshacer de un commit `AUTO` (ADR 0011); nunca
        una tool del LLM. `TODO(verify)`: endpoint real de anulación (Paso 11).

        Args:
            tenant_id: Comercio dueño del pedido.
            order_id: Pedido a anular.

        Returns:
            El pedido resultante con estado `ANULADA`.

        Raises:
            ValidationError: Si falta `tenant_id`.
            OrderNotFound: Si el pedido no existe en este comercio.
        """
        ...
