"""Entidades `Order`, `OrderItem` y `Product`: el pedido tal como lo conoce este sistema.

Estados canónicos del pedido (Paso 5): `OrderStatus` fija `ABIERTA`/`CERRADA`/`ANULADA`,
tomados del contrato real del legacy (`sahagunonline/back/src/sales_service/models.py`,
clase `OrderStatus`) — `TODO(verify)` al conectar el adapter: confirmar que el endpoint
expuesto por `ops_service` devuelve exactamente ese conjunto.

**Regla crítica (AGENTS raíz §7, capa 2)**: este modelo no tiene ningún campo ni
método para la hora del pedido. La hora la fija, lee y modifica solo el backend legacy;
al no existir en el dominio, el chatbot no puede cambiarla ni siquiera por accidente.
Hay un test de regresión que falla si aparece un campo con ese significado.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OrderStatus = Literal["ABIERTA", "CERRADA", "ANULADA"]
"""Estados canónicos del pedido (origen: `sales_service/models.py`; `TODO(verify)`)."""


class OrderItem(BaseModel):
    """Línea de un pedido: producto y cantidad pedida.

    No lleva precio ni disponibilidad: esos datos los aporta siempre el legacy
    (AGENTS raíz §5.2; el LLM jamás los calcula).

    Args:
        sku: Identificador del producto en el catálogo del comercio.
        quantity: Cantidad pedida; siempre positiva.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)


class Order(BaseModel):
    """Pedido de un comercio, ligado a su tenant.

    Modelo inmutable: no expone setters ni operaciones de modificación de la hora
    (ver la advertencia del módulo). El carrito vacío **no** se rechaza aquí sino en
    la regla de dominio correspondiente, para que `EmptyCart` siga siendo un error
    tipado con su propio mensaje.

    Args:
        id: Identificador del pedido devuelto por el backend.
        tenant_id: Comercio dueño del pedido; siempre igual al del contexto resuelto.
        items: Líneas del pedido, en el orden en que se pidieron.
        status: Estado canónico (`OrderStatus`) reportado por el legacy.
        created_at: Instante en que se registró el pedido (sale del `ClockPort`).
        total: Monto total calculado por el código desde el catálogo; jamás lo aporta
            el LLM (`TODO(verify)`: el endpoint real lo reporta).
        correlation_id: Idempotencia de la creación: la misma petición no duplica pedido.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    items: tuple[OrderItem, ...] = ()
    status: OrderStatus = Field(description="Estado canónico (OrderStatus)")
    created_at: datetime
    total: float = Field(default=0.0, ge=0)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)


class Product(BaseModel):
    """Producto del catálogo de un comercio: nombre y precio vienen del legacy.

    El precio es un dato de negocio: la tool lo lee aquí y jamás lo calcula ni lo
    inventa el LLM (AGENTS raíz §5.2).

    Args:
        tenant_id: Comercio dueño del producto (el catálogo se filtra por él).
        sku: Identificador del producto en el catálogo.
        name: Nombre visible del producto.
        price: Precio unitario reportado por el legacy.
        category: Categoría opcional para filtrar el menú.
        available: Disponibilidad actual (`False`: la tool rechaza proponerlo).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    price: float = Field(ge=0)
    category: str | None = Field(default=None, max_length=64)
    available: bool = True
