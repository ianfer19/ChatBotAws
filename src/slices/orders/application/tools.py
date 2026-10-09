"""Las tools del agente de pedidos, sobre puertos inyectados (Paso 5: propose/commit).

Ninguna tool acepta el comercio del LLM: el `tenant_id` siempre llega del estado del
turno (contexto resuelto en el gateway), igual que en los ports. `propose_order` no
escribe datos reales: crea un `PendingDraft`, aplica la política de riesgo
determinista del dominio (ítems inferidos o monto alto → `CONFIRM`) y solo el commit
(aquí mismo para `AUTO`; el router del supervisor, para `CONFIRM`) registra el pedido —
ADR 0011. Precios, disponibilidad y estado salen del catálogo y del legacy; el modelo
solo propone SKUs y cantidades. No existe tool de hora: esa operación no está en el
esquema ni en la allowlist (capa 1 de la defensa en profundidad, AGENTS raíz §7).
"""

import uuid
from collections.abc import Sequence

from shared.contracts.pending import (
    ConfirmationPolicy,
    DraftStatus,
    PendingDraft,
    compute_payload_hash,
)
from shared.errors import ValidationError
from shared.ports import ClockPort, DraftStorePort
from slices.orders.application.drafts import TTL_CONFIRMACION, commit_draft
from slices.orders.application.schemas import OrderView, ProductView, ToolResult
from slices.orders.domain.entities import Order, OrderItem, Product
from slices.orders.domain.errors import OrderNotFound, OutsideKitchenHours, ProductUnavailable
from slices.orders.domain.hours import KitchenHoursDay
from slices.orders.domain.policy import MONTO_UMBRAL, decide_order, detect_inferred_items
from slices.orders.domain.ports import CatalogPort, LegacyOrdersPort
from slices.orders.domain.rules import (
    MINIMO_COMPRA,
    check_minimum,
    validate_cart,
    within_kitchen_hours,
)


def _require_tenant(tenant_id: str) -> None:
    """Rechaza operaciones sin comercio: ninguna tool trabaja «a ciegas».

    Args:
        tenant_id: Comercio resuelto en el gateway.

    Raises:
        ValidationError: Si `tenant_id` está vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en las tools de pedidos")


def _vista(order: Order) -> OrderView:
    """Convierte un pedido del dominio en la vista que consume el prompt de redacción.

    Args:
        order: Pedido ya registrado en el legacy.

    Returns:
        Vista inmutable con los campos seguros de mostrar (sin correlación interna).
    """
    return OrderView(id=order.id, status=order.status, total=order.total, items=order.items)


def _vista_producto(product: Product) -> ProductView:
    """Convierte un producto del catálogo en su vista de respuesta.

    Args:
        product: Producto con precio y disponibilidad reales.

    Returns:
        Vista inmutable con SKU, nombre, precio y categoría.
    """
    return ProductView(
        sku=product.sku, name=product.name, price=product.price, category=product.category
    )


def _resultado_existente(
    draft: PendingDraft, *, tenant_id: str, legacy: LegacyOrdersPort
) -> ToolResult:
    """Arma el resultado de una propuesta repetida (mismo `correlation_id`).

    Args:
        draft: Draft ya creado por la petición original.
        tenant_id: Comercio del turno.
        legacy: Backend para recuperar el pedido ya registrado (si hubo commit).

    Returns:
        `ToolResult` con el estado real del draft (idempotencia, sin duplicar nada).
    """
    decision = decide_order(inferred_fields=draft.inferred_fields, total=draft.total)
    order = None
    if draft.status == DraftStatus.COMMITTED and draft.correlation_id:
        previo = legacy.find_by_correlation_id(
            tenant_id=tenant_id, correlation_id=draft.correlation_id
        )
        if previo is not None:
            order = _vista(previo)
    return ToolResult(
        tool="propose_order",
        order=order,
        draft_id=draft.draft_id,
        draft_status=draft.status,
        policy=decision.policy,
        policy_reasons=decision.reasons,
    )


class OrderTools:
    """Implementación de las cuatro tools contra catálogo, legacy y drafts.

    Example:
        >>> from datetime import datetime
        >>> from adapters.in_memory import InMemoryDraftStore
        >>> from slices.orders.infrastructure.in_memory import (
        ...     InMemoryCatalog,
        ...     InMemoryLegacyOrders,
        ...     InMemoryOrderRepository,
        ... )
        >>> class _Reloj:
        ...     def now(self) -> datetime:
        ...         return datetime(2026, 3, 2, 12, 0)
        >>> reloj = _Reloj()
        >>> tools = OrderTools(
        ...     legacy=InMemoryLegacyOrders(InMemoryOrderRepository(), clock=reloj),
        ...     catalog=InMemoryCatalog(),
        ...     drafts=InMemoryDraftStore(clock=reloj),
        ...     clock=reloj,
        ...     kitchen_hours=[],
        ... )
        >>> tools.get_menu(tenant_id="Sede_Elite_01").products
        []
    """

    def __init__(
        self,
        *,
        legacy: LegacyOrdersPort,
        catalog: CatalogPort,
        drafts: DraftStorePort,
        clock: ClockPort,
        kitchen_hours: Sequence[KitchenHoursDay],
        minimum: float = MINIMO_COMPRA,
        amount_threshold: float = MONTO_UMBRAL,
    ) -> None:
        """Guarda los puertos con los que trabaja cada llamada.

        Args:
            legacy: Backend de pedidos (doble en memoria hasta el Paso 11).
            catalog: Catálogo de productos del comercio.
            drafts: Store de propuestas pendientes (ADR 0011; DynamoDB en el Paso 6).
            clock: Reloj inyectable (horario de cocina y ventana de deshacer).
            kitchen_hours: Horario de cocina del comercio (falso hasta RAG/Paso 7).
            minimum: Mínimo de compra del comercio (pesos).
            amount_threshold: Monto desde el cual el pedido exige confirmación.
        """
        self._legacy = legacy
        self._catalog = catalog
        self._drafts = drafts
        self._clock = clock
        self._hours = tuple(kitchen_hours)
        self._minimum = minimum
        self._umbral = amount_threshold

    def search_products(self, *, tenant_id: str, query: str) -> ToolResult:
        """Busca productos en el catálogo del comercio (regla 4: precio real, no inventado).

        Args:
            tenant_id: Comercio resuelto en el gateway.
            query: Término escrito por el cliente.

        Returns:
            `ToolResult` con los productos coincidentes (vistas con precio real).

        Raises:
            ValidationError: Si falta `tenant_id` o `query`.
        """
        _require_tenant(tenant_id)
        encontrados = self._catalog.search(tenant_id=tenant_id, query=query)
        return ToolResult(
            tool="search_products", products=[_vista_producto(p) for p in encontrados]
        )

    def get_menu(self, *, tenant_id: str, category: str | None = None) -> ToolResult:
        """Menú del comercio, con precios reales del catálogo (reglas 1 y 4).

        Args:
            tenant_id: Comercio resuelto en el gateway.
            category: Categoría opcional a filtrar.

        Returns:
            `ToolResult` con los productos del menú.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        productos = self._catalog.list_menu(tenant_id=tenant_id, category=category)
        return ToolResult(tool="get_menu", products=[_vista_producto(p) for p in productos])

    def get_order_status(self, *, tenant_id: str, order_id: str) -> ToolResult:
        """Estado de un pedido del comercio (regla 1: nunca expone pedidos ajenos).

        Args:
            tenant_id: Comercio resuelto en el gateway.
            order_id: Pedido a consultar.

        Returns:
            `ToolResult` con el pedido encontrado.

        Raises:
            ValidationError: Si falta `tenant_id`.
            OrderNotFound: Si el pedido no existe en este comercio.
        """
        _require_tenant(tenant_id)
        pedido = self._legacy.get_order_status(tenant_id=tenant_id, order_id=order_id)
        if pedido is None:
            raise OrderNotFound(
                "pedido no encontrado en este comercio", details={"order_id": order_id}
            )
        return ToolResult(tool="get_order_status", order=_vista(pedido))

    def propose_order(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        conversation_id: str,
        message: str,
        items: Sequence[OrderItem],
    ) -> ToolResult:
        """Propone un pedido como draft y aplica la política de riesgo (ADR 0011).

        Orden de validaciones: carrito no vacío (regla 5) → idempotencia →
        disponibilidad en el catálogo (reglas 4 y 5) → mínimo de compra y horario de
        cocina (regla 6) → política de riesgo (ítems inferidos o monto alto → `CONFIRM`).
        Solo `AUTO` materializa el pedido (con ventana de deshacer de 30 min).

        Args:
            tenant_id: Comercio resuelto en el gateway.
            correlation_id: Clave de idempotencia: repetir la petición no duplica draft.
            conversation_id: Conversación dueña del draft (un solo activo por ella).
            message: Mensaje crudo del cliente (detecta ítems inferidos).
            items: Carrito propuesto (SKU y cantidad; precios los pone el catálogo).

        Returns:
            `ToolResult` con el pedido registrado (`AUTO`) o solo el draft a la espera
            (`CONFIRM`), incluyendo `draft_id`, `draft_status` y `policy`.

        Raises:
            ValidationError: Si falta `tenant_id`.
            EmptyCart: Si el carrito está vacío (regla 5).
            ProductUnavailable: Si un SKU no existe o no está disponible (reglas 4 y 5).
            MinimumNotMet: Si el total no alcanza el mínimo de compra (regla 6).
            OutsideKitchenHours: Si ahora no hay cocina abierta (regla 6).
        """
        _require_tenant(tenant_id)
        validate_cart(items)

        previo = self._drafts.find_by_correlation_id(
            tenant_id=tenant_id, correlation_id=correlation_id
        )
        if previo is not None:
            return _resultado_existente(previo, tenant_id=tenant_id, legacy=self._legacy)

        productos, total = self._resolver_items(tenant_id=tenant_id, items=items)
        check_minimum(total=total, minimum=self._minimum)
        ahora = self._clock.now()
        if not within_kitchen_hours(now=ahora, schedule=self._hours):
            raise OutsideKitchenHours(
                "fuera del horario de cocina",
                details={"ahora": ahora.isoformat(timespec="minutes")},
            )

        inferidos = detect_inferred_items(
            message=message,
            items=[
                (item.sku, producto.name) for item, producto in zip(items, productos, strict=True)
            ],
        )
        decision = decide_order(inferred_fields=inferidos, total=total, umbral=self._umbral)
        payload: dict[str, object] = {
            "op": "create",
            "items": [{"sku": item.sku, "quantity": item.quantity} for item in items],
            "total": total,
        }
        draft = self._nuevo_draft(
            payload=payload,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            inferred=inferidos,
            total=total,
        )
        self._drafts.save(tenant_id=tenant_id, draft=draft)
        if decision.policy is ConfirmationPolicy.AUTO:
            return self._commitear(
                draft.model_copy(update={"status": DraftStatus.AUTO_APPROVED}),
                tenant_id=tenant_id,
                decision_policy=decision.policy,
                reasons=decision.reasons,
            )
        pendiente = draft.model_copy(update={"status": DraftStatus.AWAITING_CONFIRMATION})
        self._drafts.save(tenant_id=tenant_id, draft=pendiente)
        return ToolResult(
            tool="propose_order",
            draft_id=pendiente.draft_id,
            draft_status=pendiente.status,
            policy=decision.policy,
            policy_reasons=decision.reasons,
        )

    def _resolver_items(
        self, *, tenant_id: str, items: Sequence[OrderItem]
    ) -> tuple[list[Product], float]:
        """Resuelve cada SKU contra el catálogo y calcula el total (código, no el LLM).

        Args:
            tenant_id: Comercio dueño del carrito.
            items: Carrito propuesto.

        Returns:
            Tupla `(productos_resueltos, total)` en el mismo orden que `items`.

        Raises:
            ProductUnavailable: Si un SKU no existe en este comercio o no está
                disponible (regla 5).
        """
        productos: list[Product] = []
        total = 0.0
        for item in items:
            producto = self._catalog.find_by_sku(tenant_id=tenant_id, sku=item.sku)
            if producto is None or not producto.available:
                raise ProductUnavailable(
                    "producto inexistente o no disponible",
                    details={"sku": item.sku},
                )
            productos.append(producto)
            total += producto.price * item.quantity
        return productos, total

    def _nuevo_draft(
        self,
        *,
        payload: dict[str, object],
        tenant_id: str,
        conversation_id: str,
        correlation_id: str,
        inferred: tuple[str, ...],
        total: float,
    ) -> PendingDraft:
        """Arma el draft recién propuesto (estado inicial `DRAFTED`).

        Args:
            payload: Contenido exacto propuesto (se hashea al construirlo).
            tenant_id: Comercio dueño del draft.
            conversation_id: Conversación a la que pertenece.
            correlation_id: Idempotencia de la propuesta.
            inferred: SKUs inferidos por el LLM (disparan `CONFIRM`).
            total: Monto total calculado desde el catálogo.

        Returns:
            El draft listo para guardarse.
        """
        ahora = self._clock.now()
        return PendingDraft(
            draft_id=f"drf-{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            kind="order",
            status=DraftStatus.DRAFTED,
            payload={**payload},
            inferred_fields=inferred,
            total=total,
            payload_hash=compute_payload_hash({**payload}),
            correlation_id=correlation_id,
            created_at=ahora,
            expires_at=ahora + TTL_CONFIRMACION,
        )

    def _commitear(
        self,
        draft: PendingDraft,
        *,
        tenant_id: str,
        decision_policy: ConfirmationPolicy,
        reasons: tuple[str, ...],
    ) -> ToolResult:
        """Marca el draft `AUTO_APPROVED`, lo commitea y arma el resultado.

        Args:
            draft: Draft propuesto (se guarda en `AUTO_APPROVED` antes del commit).
            tenant_id: Comercio dueño del draft.
            decision_policy: Política aplicada (siempre `AUTO` en esta ruta).
            reasons: Motivos de la política para logs y tests.

        Returns:
            `ToolResult` con el pedido ya registrado.

        Raises:
            DraftNotFound: Si el draft desaparece entre guardar y commitear (no debe).
            DraftNotCommittable: Si un estado intermedio rompe la máquina (no debe).
        """
        self._drafts.save(tenant_id=tenant_id, draft=draft)
        pedido = commit_draft(
            tenant_id=tenant_id,
            draft_id=draft.draft_id,
            legacy=self._legacy,
            drafts=self._drafts,
            clock=self._clock,
        )
        return ToolResult(
            tool="propose_order",
            order=_vista(pedido),
            draft_id=draft.draft_id,
            draft_status=DraftStatus.COMMITTED,
            policy=decision_policy,
            policy_reasons=reasons,
        )
