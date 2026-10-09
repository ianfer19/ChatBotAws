"""Tests de las tools de pedidos sobre dobles en memoria (Paso 5: propose/commit)."""

from datetime import datetime
from typing import get_args

import pytest

from adapters.in_memory import InMemoryDraftStore
from shared.contracts.pending import ConfirmationPolicy, DraftStatus
from slices.orders.application.schemas import KitchenHoursDay, ToolName, ToolResult
from slices.orders.application.tools import OrderTools
from slices.orders.domain.entities import OrderItem, Product
from slices.orders.domain.errors import (
    EmptyCart,
    MinimumNotMet,
    OrderNotFound,
    OutsideKitchenHours,
    ProductUnavailable,
)
from slices.orders.domain.policy import MOTIVO_MONTO
from slices.orders.infrastructure.in_memory import (
    InMemoryCatalog,
    InMemoryLegacyOrders,
    InMemoryOrderRepository,
)

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Otro_Comercio_01"
CONVERSACION = "whatsapp:57300111111"

COCINA_LUNES = KitchenHoursDay(weekday=0, open_time="11:00", close_time="15:00")
MINIMO = 10_000.0
UMBRAL = 100_000.0

CATALOGO = (
    Product(tenant_id=TENANT, sku="A-100", name="Alitas BBQ", price=18_000, category="entradas"),
    Product(
        tenant_id=TENANT, sku="A-200", name="Papas con queso", price=12_000, category="entradas"
    ),
    Product(tenant_id=TENANT, sku="P-100", name="Coca-Cola", price=5_000, category="bebidas"),
    Product(
        tenant_id=TENANT,
        sku="A-900",
        name="Combo agotado",
        price=20_000,
        category="entradas",
        available=False,
    ),
    Product(
        tenant_id=OTRO_TENANT, sku="X-100", name="Producto ajeno", price=9_000, category="bebidas"
    ),
)
# Mensaje con los nombres literales de los ítems: la política puede ir a `AUTO`.
_MSG_EXPLICITA = "quiero Alitas BBQ y una Coca-Cola"


class _RelojFijo:
    """Reloj inyectable con hora fija: decide si hay cocina abierta."""

    def __init__(self, ahora: datetime) -> None:
        """Guarda el instante que devolverá `now`.

        Args:
            ahora: Instante fijo del test.
        """
        self._ahora = ahora

    def now(self) -> datetime:
        """Devuelve el instante fijo del test.

        Returns:
            La hora configurada al construir el reloj.
        """
        return self._ahora


def _tools(
    *,
    ahora: datetime = datetime(2026, 3, 2, 12, 0),
    horario: tuple[KitchenHoursDay, ...] = (COCINA_LUNES,),
    minimum: float = MINIMO,
    amount_threshold: float = UMBRAL,
) -> tuple[OrderTools, InMemoryLegacyOrders, InMemoryOrderRepository, InMemoryDraftStore]:
    """Construye las tools con dobles en memoria y cocina abierta el lunes.

    Args:
        ahora: Hora del reloj fijo.
        horario: Horario de cocina inyectado.
        minimum: Mínimo de compra del comercio de prueba.
        amount_threshold: Monto desde el cual se exige confirmación.

    Returns:
        Tupla con las tools, el doble del legacy, su repositorio y el store de drafts.
    """
    reloj = _RelojFijo(ahora)
    repo = InMemoryOrderRepository()
    legacy = InMemoryLegacyOrders(repo, clock=reloj)
    drafts = InMemoryDraftStore(clock=reloj)
    tools = OrderTools(
        legacy=legacy,
        catalog=InMemoryCatalog(CATALOGO),
        drafts=drafts,
        clock=reloj,
        kitchen_hours=horario,
        minimum=minimum,
        amount_threshold=amount_threshold,
    )
    return tools, legacy, repo, drafts


def _proponer(
    tools: OrderTools,
    *,
    items: tuple[OrderItem, ...] = (
        OrderItem(sku="A-100", quantity=2),
        OrderItem(sku="P-100", quantity=1),
    ),
    message: str = _MSG_EXPLICITA,
    correlation_id: str = "corr-1",
) -> ToolResult:
    """Propone un pedido con la firma real de la tool.

    Args:
        tools: Tools bajo prueba.
        items: Carrito propuesto.
        message: Mensaje crudo (decide qué ítems se dan por dichos).
        correlation_id: Idempotencia de la propuesta.

    Returns:
        El `ToolResult` de la propuesta.
    """
    return tools.propose_order(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        conversation_id=CONVERSACION,
        message=message,
        items=items,
    )


def test_busqueda_devuelve_productos_con_el_precio_del_catalogo() -> None:
    """El precio sale del catálogo (dato de negocio), nunca lo inventa el modelo."""
    tools, *_ = _tools()
    result = tools.search_products(tenant_id=TENANT, query="alitas")
    assert result.tool == "search_products"
    assert [(p.sku, p.price) for p in result.products] == [("A-100", 18_000.0)]


def test_menu_filtra_por_categoria_y_por_comercio() -> None:
    """El menú solo muestra productos de este comercio y de la categoría pedida."""
    tools, *_ = _tools()
    bebidas = tools.get_menu(tenant_id=TENANT, category="bebidas")
    assert [p.sku for p in bebidas.products] == ["P-100"]
    ajeno = tools.get_menu(tenant_id=OTRO_TENANT)
    assert [p.sku for p in ajeno.products] == ["X-100"]


def test_consulta_de_pedido_desconocido_o_ajeno_se_rechaza() -> None:
    """Pedidos inexistentes o de otro comercio se reportan como no encontrados (regla 1)."""
    tools, legacy, _, _ = _tools()
    with pytest.raises(OrderNotFound):
        tools.get_order_status(tenant_id=TENANT, order_id="ord-no-existe")
    ajeno = legacy.create_order(
        tenant_id=OTRO_TENANT,
        correlation_id="corr-ajeno",
        items=(OrderItem(sku="X-100", quantity=1),),
        total=9_000,
    )
    with pytest.raises(OrderNotFound):
        tools.get_order_status(tenant_id=TENANT, order_id=ajeno.id)


def test_propuesta_explicita_se_commitea_auto() -> None:
    """Con los nombres literales la política es `AUTO`: pedido creado y total calculado."""
    tools, legacy, repo, drafts = _tools()
    result = _proponer(tools)
    assert result.order is not None
    assert result.order.status == "ABIERTA"
    assert result.order.total == 18_000 * 2 + 5_000
    assert result.policy is ConfirmationPolicy.AUTO
    assert result.draft_status is DraftStatus.COMMITTED
    assert result.draft_id is not None
    guardado = legacy.get_order_status(tenant_id=TENANT, order_id=result.order.id)
    assert guardado is not None and guardado.tenant_id == TENANT
    draft = drafts.get(tenant_id=TENANT, draft_id=result.draft_id)
    assert draft is not None and draft.undo_until is not None
    assert [o.id for o in repo.list_for_tenant(tenant_id=TENANT)] == [result.order.id]


def test_propuesta_con_items_inferidos_queda_a_la_espera() -> None:
    """Si el modelo infirió productos la política exige `CONFIRM`: nada se registra."""
    tools, _, repo, drafts = _tools()
    result = _proponer(tools, message="quiero pedir algo para la tarde")
    assert result.order is None
    assert result.policy is ConfirmationPolicy.CONFIRM
    assert result.draft_status is DraftStatus.AWAITING_CONFIRMATION
    assert MOTIVO_MONTO not in result.policy_reasons
    assert result.policy_reasons == ("item_inferido:A-100", "item_inferido:P-100")
    assert repo.list_for_tenant(tenant_id=TENANT) == []
    draft = drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION)
    assert draft is not None and draft.status is DraftStatus.AWAITING_CONFIRMATION


def test_propuesta_de_producto_desconocido_no_crea_draft() -> None:
    """Un SKU que no existe en el catálogo rechaza la propuesta entera (reglas 4 y 5)."""
    tools, _, repo, drafts = _tools()
    with pytest.raises(ProductUnavailable) as excinfo:
        _proponer(tools, items=(OrderItem(sku="ZZ-999", quantity=1),), message="quiero ZZ-999")
    assert excinfo.value.details["sku"] == "ZZ-999"
    assert repo.list_for_tenant(tenant_id=TENANT) == []
    assert drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION) is None


def test_propuesta_de_producto_agotado_no_crea_draft() -> None:
    """Un producto sin disponibilidad tampoco entra en la propuesta (regla 5)."""
    tools, _, repo, _ = _tools()
    with pytest.raises(ProductUnavailable):
        _proponer(
            tools,
            items=(OrderItem(sku="A-900", quantity=1),),
            message="quiero Combo agotado",
        )
    assert repo.list_for_tenant(tenant_id=TENANT) == []


def test_propuesta_bajo_el_minimo_se_rechaza() -> None:
    """El total calculado no alcanza el mínimo de compra: error tipado con montos."""
    tools, _, repo, _ = _tools()
    with pytest.raises(MinimumNotMet) as excinfo:
        _proponer(
            tools,
            items=(OrderItem(sku="P-100", quantity=1),),
            message="quiero una Coca-Cola",
        )
    assert excinfo.value.details["total"] == "5000.0"
    assert repo.list_for_tenant(tenant_id=TENANT) == []


def test_propuesta_fuera_del_horario_de_cocina_se_rechaza() -> None:
    """A las 16:00 no hay cocina: la regla 6 falla antes de crear draft alguno."""
    tools, _, repo, drafts = _tools(ahora=datetime(2026, 3, 2, 16, 0))
    with pytest.raises(OutsideKitchenHours):
        _proponer(tools)
    assert repo.list_for_tenant(tenant_id=TENANT) == []
    assert drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION) is None


def test_propuesta_es_idempotente_por_correlation_id() -> None:
    """Repetir la misma petición devuelve el mismo draft y no duplica el pedido."""
    tools, _, repo, _ = _tools()
    primera = _proponer(tools, correlation_id="corr-reintento")
    segunda = _proponer(tools, correlation_id="corr-reintento")
    assert primera.draft_id == segunda.draft_id
    assert primera.order is not None and segunda.order is not None
    assert primera.order.id == segunda.order.id
    assert len(repo.list_for_tenant(tenant_id=TENANT)) == 1


def test_carrito_vacio_no_llega_a_ninguna_regla() -> None:
    """La regla 5 rechaza el carrito vacío antes de idempotencia o catálogo."""
    tools, _, repo, _ = _tools()
    with pytest.raises(EmptyCart):
        _proponer(tools, items=())
    assert repo.list_for_tenant(tenant_id=TENANT) == []


def test_monto_alto_exige_confirmacion_iguales_dicho() -> None:
    """Todo literal en el mensaje pero el total llega al umbral: `CONFIRM` por monto."""
    tools, _, repo, _ = _tools(amount_threshold=1_000)
    result = _proponer(tools)
    assert result.order is None
    assert result.policy is ConfirmationPolicy.CONFIRM
    assert result.policy_reasons == (MOTIVO_MONTO,)
    assert repo.list_for_tenant(tenant_id=TENANT) == []


def test_no_existe_ninguna_tool_de_hora_en_la_allowlist() -> None:
    """Capa 1 de la defensa en profundidad: el esquema no conoce la hora del pedido."""
    assert set(get_args(ToolName)) == {
        "search_products",
        "get_menu",
        "get_order_status",
        "propose_order",
    }
    assert not any(
        "hour" in nombre or "time" in nombre or "schedule" in nombre
        for nombre in get_args(ToolName)
    )
