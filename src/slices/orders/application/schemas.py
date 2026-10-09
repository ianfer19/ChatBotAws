"""Modelos Pydantic de la aplicación: lo que el LLM propone y lo que devuelven las tools.

Espejo de `appointments/application/schemas.py` (decisión del Paso 3): los contratos
públicos hacia otros slices se publican en `shared/contracts/` cuando haga falta; nada
de aquí viaja al `domain/`. `KitchenHoursDay` se re-exporta porque lo necesita la regla
de horario de cocina (Paso 5).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.pending import ConfirmationPolicy, DraftStatus
from slices.orders.domain.entities import OrderItem, OrderStatus
from slices.orders.domain.hours import KitchenHoursDay

__all__ = [
    "KitchenHoursDay",
    "OrderProposal",
    "OrderStatus",
    "OrderView",
    "ProductView",
    "ProposalAction",
    "ToolName",
    "ToolResult",
]

ToolName = Literal[
    "search_products",
    "get_menu",
    "get_order_status",
    "propose_order",
]
"""Tools que este grafo sabe ejecutar (allowlist; «LangGraph decide si puede usarla»).

Solo `propose_order` propone escrituras y lo hace como draft: ninguna tool escribe
datos reales directamente (ADR 0011.1). No existe tool de hora: la regla crítica
prohíbe incluso su mención en el esquema (capa 1, defensa en profundidad).
"""

ProposalAction = Literal[ToolName, "reply"]
"""Acción propuesta por el LLM: una tool o `reply` (sin herramienta)."""


class OrderProposal(BaseModel):
    """Conclusión de `understand` sobre el turno, ya validada contra el esquema.

    El modelo es `extra="forbid"`: si el LLM añade campos ajenos (p. ej. `tenant_id`
    o cualquier campo de hora), el parseo falla y el turno cae a la ruta de aclaración —
    el aislamiento por tenant y la regla crítica no dependen de lo que el modelo escriba.

    Args:
        action: Tool a ejecutar o `reply` si no hay nada que ejecutar.
        query: Término de búsqueda de productos.
        category: Categoría del menú a filtrar.
        order_id: Pedido a consultar.
        items: Carrito propuesto (SKU y cantidad; precios jamás los aporta el LLM).
        reply: Pista de texto cuando `action="reply"` (saludo, aclaración).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ProposalAction
    query: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=64)
    order_id: str | None = Field(default=None, max_length=64)
    items: tuple[OrderItem, ...] = ()
    reply: str | None = Field(default=None, max_length=500)


class ProductView(BaseModel):
    """Producto del catálogo listo para redactar (precio real, nunca calculado)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    price: float = Field(ge=0)
    category: str | None = Field(default=None, max_length=64)


class OrderView(BaseModel):
    """Vista de un pedido para redactar la respuesta (sin datos internos de más)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    status: OrderStatus
    total: float = Field(ge=0)
    items: tuple[OrderItem, ...] = ()


class ToolResult(BaseModel):
    """Salida de una tool del grafo: la única fuente de datos de la respuesta.

    Args:
        tool: Tool que produjo el resultado (debe coincidir con la pedida).
        products: Productos devueltos por catálogo/menú (`search`/`get_menu`).
        order: Pedido consultado o creado (`get_order_status`, `propose_order` en `AUTO`).
        draft_id: Draft asociado a la propuesta (solo tools de escritura).
        draft_status: Estado del draft en la máquina del ADR 0011.
        policy: Política aplicada (`AUTO` directo o `CONFIRM` a la espera).
        policy_reasons: Motivos de la política (logs, métricas y tests).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ToolName
    products: list[ProductView] = Field(default_factory=list)
    order: OrderView | None = None
    draft_id: str | None = None
    draft_status: DraftStatus | None = None
    policy: ConfirmationPolicy | None = None
    policy_reasons: tuple[str, ...] = ()
