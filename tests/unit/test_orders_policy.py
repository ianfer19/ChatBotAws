"""Tests de la política de riesgo de pedidos: ítems inferidos, monto y decisión (ADR 0011)."""

from shared.contracts.pending import ConfirmationPolicy
from slices.orders.domain.policy import (
    MOTIVO_MONTO,
    decide_order,
    detect_inferred_items,
)

# (sku, nombre) del catálogo para el carrito de prueba.
_ITEMS = (("A-100", "Alitas BBQ"), ("P-100", "Coca-Cola"))


def test_todo_lo_literal_en_el_mensaje_no_infiere_nada() -> None:
    """Con los nombres de los productos escritos no hay nada inferido."""
    inferidos = detect_inferred_items(message="quiero Alitas BBQ y una Coca-Cola", items=_ITEMS)
    assert inferidos == ()


def test_el_sku_tambien_cuenta_como_dicho() -> None:
    """Mencionar el SKU («A-100») da por dicho ese ítem aunque no su nombre."""
    inferidos = detect_inferred_items(message="pídemelo con el A-100", items=_ITEMS)
    assert inferidos == ("P-100",)


def test_la_comparacion_ignora_mayusculas_y_acentos() -> None:
    """«ALITAS BBQ» en el mensaje da por dicho «Alitas BBQ»."""
    inferidos = detect_inferred_items(message="ALITAS BBQ y Coca-Cola", items=_ITEMS)
    assert inferidos == ()


def test_un_item_no_mencionado_se_marca_inferido() -> None:
    """Si el cliente no mencionó un producto, el modelo lo infirió: dispara `CONFIRM`."""
    inferidos = detect_inferred_items(message="quiero Alitas BBQ", items=_ITEMS)
    assert inferidos == ("P-100",)


def test_sin_mencion_nada_todo_se_marca_inferido() -> None:
    """Mensaje vacío: todos los ítems cuentan como inferidos, en orden de carrito."""
    inferidos = detect_inferred_items(message="", items=_ITEMS)
    assert inferidos == ("A-100", "P-100")


def test_decide_todo_dicho_y_bajo_el_umbral_es_auto() -> None:
    """Sin inferidos y con monto bajo: se ejecuta solo, con ventana de deshacer."""
    decision = decide_order(inferred_fields=(), total=30_000, umbral=100_000)
    assert decision.policy is ConfirmationPolicy.AUTO
    assert decision.reasons == ()


def test_decide_con_items_inferidos_es_confirm_con_motivos() -> None:
    """Un solo ítem inferido ya exige confirmación, con su motivo trazable."""
    decision = decide_order(inferred_fields=("P-100",), total=30_000, umbral=100_000)
    assert decision.policy is ConfirmationPolicy.CONFIRM
    assert decision.reasons == ("item_inferido:P-100",)


def test_decide_un_monto_alto_es_confirm_igual() -> None:
    """Todo dicho pero el total llega al umbral: igual exige confirmación."""
    decision = decide_order(inferred_fields=(), total=150_000, umbral=100_000)
    assert decision.policy is ConfirmationPolicy.CONFIRM
    assert decision.reasons == (MOTIVO_MONTO,)


def test_decide_con_dos_sensores_acumula_los_motivos() -> None:
    """Ítems inferidos y monto alto se reportan juntos, en ese orden."""
    decision = decide_order(inferred_fields=("A-100", "P-100"), total=200_000, umbral=100_000)
    assert decision.policy is ConfirmationPolicy.CONFIRM
    assert decision.reasons == ("item_inferido:A-100", "item_inferido:P-100", MOTIVO_MONTO)
