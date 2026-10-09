"""Reglas de negocio puras del turno de pedidos (Paso 5).

- Regla 5: carrito con ítems antes de cualquier llamada externa (cantidades positivas
  y disponibilidad se validan en `OrderItem` y en las tools con el catálogo).
- Regla 6: mínimo de compra y horario de cocina del comercio.

`TODO(decision)`: valores de `MINIMO_COMPRA` y del horario de cocina por comercio (hoy
constantes de referencia que la composición puede inyectar).
"""

from collections.abc import Sequence
from datetime import datetime, time

from .entities import OrderItem
from .errors import EmptyCart, MinimumNotMet
from .hours import KitchenHoursDay

MINIMO_COMPRA = 10_000.0
"""Monto mínimo de compra de referencia (pesos); la composición puede inyectar otro."""


def validate_cart(items: Sequence[OrderItem]) -> None:
    """Valida que el carrito tenga al menos un ítem antes de proponer el pedido.

    Args:
        items: Ítems propuestos por el modelo (cantidades ya validadas positivas
            por `OrderItem`).

    Raises:
        EmptyCart: Si `items` está vacío.
    """
    if not items:
        raise EmptyCart("carrito sin ítems")


def check_minimum(*, total: float, minimum: float) -> None:
    """Valida que el total del pedido alcance el mínimo de compra.

    Args:
        total: Monto total calculado desde el catálogo.
        minimum: Mínimo de compra del comercio (pesos).

    Raises:
        MinimumNotMet: Si `total` es menor que `minimum`.
    """
    if total < minimum:
        raise MinimumNotMet(
            "total por debajo del mínimo",
            details={"total": str(total), "minimo": str(minimum)},
        )


def within_kitchen_hours(*, now: datetime, schedule: Sequence[KitchenHoursDay]) -> bool:
    """Indica si la hora actual cae dentro del horario de cocina del comercio.

    La franja se evalúa en hora local naive (misma convención que las citas); un día
    sin franja nunca está dentro y los extremos se consideran abiertos
    (`apertura <= hora <= cierre`).

    Args:
        now: Instante actual (sale del `ClockPort`).
        schedule: Franjas de cocina inyectadas (horario del comercio).

    Returns:
        `True` si hay cocina abierta; `False` en caso contrario.
    """
    dia = now.date()
    hora = now.time()
    for bloque in schedule:
        if bloque.weekday != dia.weekday():
            continue
        apertura = time.fromisoformat(bloque.open_time)
        cierre = time.fromisoformat(bloque.close_time)
        if apertura <= hora <= cierre:
            return True
    return False
