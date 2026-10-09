"""Errores tipados del dominio de pedidos: los nodos y tools los traducen a respuesta.

Subclases de `shared.errors.AppError` con `code` estable para logs, métricas y tests;
el mensaje es para el log, nunca se muestra tal cual al usuario final.

`DraftNotFound` y `DraftNotCommittable` son espejo de los de `appointments`: cada slice
es dueño de los suyos (los slices no se importan entre sí) y el store compartido impone
la misma máquina de estados del ADR 0011.

`TODO(decision)`: `LegacyTimeout` y `PaymentRejected` los lanza el adapter del backend
legacy (Paso 11); hoy existen solo como contrato del slice y no se lanzan aún.
"""

from shared.errors import AppError


class EmptyCart(AppError):
    """El carrito no tiene ítems: no se propone ni se consulta nada."""

    code = "empty_cart"
    http_status = 400


class ProductUnavailable(AppError):
    """SKU inexistente en el catálogo o sin disponibilidad (regla 5)."""

    code = "product_unavailable"
    http_status = 409


class OutsideKitchenHours(AppError):
    """Fuera del horario de cocina del comercio (regla 6)."""

    code = "outside_kitchen_hours"
    http_status = 422


class MinimumNotMet(AppError):
    """El total del pedido no alcanza el mínimo de compra (regla 6)."""

    code = "minimum_not_met"
    http_status = 422


class OrderNotFound(AppError):
    """No hay ningún pedido con ese identificador en este comercio."""

    code = "order_not_found"
    http_status = 404


class PaymentRejected(AppError):
    """El legacy rechazó el pago: se informa tal cual y nunca se reintenta (regla 7)."""

    code = "payment_rejected"
    http_status = 402


class LegacyTimeout(AppError):
    """El backend legacy no respondió dentro del timeout configurado."""

    code = "legacy_timeout"
    http_status = 504


class DraftNotFound(AppError):
    """No hay ningún draft con ese identificador en este comercio."""

    code = "draft_not_found"
    http_status = 404


class DraftNotCommittable(AppError):
    """El draft no está en un estado que admita la transición pedida (ADR 0011)."""

    code = "draft_not_committable"
    http_status = 409
