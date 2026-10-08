"""Entidades `Order` y `OrderItem`: el pedido tal como lo conoce este sistema.

Contrato previo del Paso 1: los campos necesarios para tipar puertos y dobles; las
reglas (carrito, mínimo de compra, horario de cocina) llegan con el Paso 5.

**Regla crítica (AGENTS raíz §7, capa 2)**: este modelo no tiene ningún campo ni
método para la hora del pedido. La hora la fija, lee y modifica solo el backend legacy;
al no existir en el dominio, el chatbot no puede cambiarla ni siquiera por accidente.
Hay un test de regresión que falla si aparece un campo con ese significado.

`TODO(decision)`: estados canónicos del pedido y su transiciones se fijan en el Paso 5,
cuando se lea el contrato real de las APIs de pedidos
(`sahagunonline/back/catalogo_endpoints.md`).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
        status: Estado crudo reportado por el legacy (ver `TODO(decision)` del módulo).
        created_at: Instante en que se registró el pedido (sale del `ClockPort`).
        correlation_id: Idempotencia de la creación: la misma petición no duplica pedido.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    items: tuple[OrderItem, ...] = ()
    status: str = Field(min_length=1, max_length=32)
    created_at: datetime
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)
