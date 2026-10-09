"""Política de riesgo de los pedidos: decide `AUTO` o `CONFIRM` sin LLM (ADR 0011.3).

La política es código determinista testeable. Regla v1 (conservadora, calibrar con
métricas reales en el Paso 13):

- un ítem que el cliente no mencionó literalmente (ni su SKU ni su nombre) cuenta como
  inferido → `CONFIRM` con motivo `item_inferido:<sku>`;
- un total igual o mayor que `MONTO_UMBRAL` → `CONFIRM` con motivo `monto_sobre_umbral`.

`TODO(verify)`: la cantidad se da por dicha si el producto se mencionó (v1 simple);
calibrar con tráfico real.
"""

import unicodedata
from collections.abc import Sequence

from shared.contracts.pending import ConfirmationPolicy, PolicyDecision

MONTO_UMBRAL = 100_000.0
"""Monto (pesos) desde el cual el pedido exige confirmación explícita."""

MOTIVO_MONTO = "monto_sobre_umbral"
"""Motivo estándar de `CONFIRM` por monto alto."""


def _normalizar(texto: str) -> str:
    """Normaliza un texto para compararlo: minúsculas y sin acentos.

    Args:
        texto: Cadena de entrada (mensaje del cliente o valor de un campo).

    Returns:
        La cadena en minúsculas sin marcas diacríticas.
    """
    base = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(caracter for caracter in base if not unicodedata.combining(caracter))


def detect_inferred_items(*, message: str, items: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """Detecta los ítems que el LLM infirió en lugar de decirlos el cliente.

    Un ítem se da por dicho si su SKU o su nombre literal aparece en el mensaje
    («alitas», «A-100»). Heurística conservadora: ante la duda el ítem cuenta como
    inferido y la política exige confirmación.

    Args:
        message: Texto crudo del mensaje del cliente.
        items: Ítems propuestos con su `(sku, nombre)` del catálogo.

    Returns:
        SKUs de los ítems inferidos, en el orden de `items`; vacío si todo se dijo.
    """
    mensaje = _normalizar(message)
    inferidos: list[str] = []
    for sku, nombre in items:
        if _normalizar(sku) in mensaje or _normalizar(nombre) in mensaje:
            continue
        inferidos.append(sku)
    return tuple(inferidos)


def decide_order(
    *, inferred_fields: Sequence[str], total: float, umbral: float = MONTO_UMBRAL
) -> PolicyDecision:
    """Aplica la política de riesgo a un pedido recién armado.

    Args:
        inferred_fields: SKUs inferidos devueltos por `detect_inferred_items`.
        total: Monto total calculado desde el catálogo.
        umbral: Monto desde el cual el pedido exige confirmación.

    Returns:
        `PolicyDecision` con `AUTO` (sin motivos) o `CONFIRM` (un motivo por señal,
        para logs y tests).
    """
    motivos = [f"item_inferido:{sku}" for sku in inferred_fields]
    if total >= umbral:
        motivos.append(MOTIVO_MONTO)
    if motivos:
        return PolicyDecision(policy=ConfirmationPolicy.CONFIRM, reasons=tuple(motivos))
    return PolicyDecision(policy=ConfirmationPolicy.AUTO)
