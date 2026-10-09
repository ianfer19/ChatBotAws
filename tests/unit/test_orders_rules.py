"""Tests de las reglas de dominio de pedidos: carrito, mínimo de compra y cocina (reglas 5 y 6)."""

from datetime import datetime

import pytest

from slices.orders.domain.entities import OrderItem
from slices.orders.domain.errors import EmptyCart, MinimumNotMet
from slices.orders.domain.hours import KitchenHoursDay
from slices.orders.domain.rules import check_minimum, validate_cart, within_kitchen_hours

COCINA_LUNES = KitchenHoursDay(weekday=0, open_time="11:00", close_time="15:00")
LUNES_2026_03_02 = datetime(2026, 3, 2, 12, 0)


def test_carrito_vacio_se_rechaza() -> None:
    """Sin ítems no se propone nada: la regla 5 falla antes de tocar el legacy."""
    with pytest.raises(EmptyCart):
        validate_cart([])


def test_carrito_con_items_pasa() -> None:
    """Un carrito con al menos un ítem (cantidad ya validada en la entidad) es válido."""
    validate_cart([OrderItem(sku="A-100", quantity=2)])


def test_minimo_de_compra_por_debajo_se_rechaza_con_detalles() -> None:
    """Total menor que el mínimo: error tipado con el total y el mínimo para el log."""
    with pytest.raises(MinimumNotMet) as excinfo:
        check_minimum(total=5_000.0, minimum=10_000.0)
    assert excinfo.value.details["total"] == "5000.0"
    assert excinfo.value.details["minimo"] == "10000.0"


def test_minimo_de_compra_igual_o_mayor_pasa() -> None:
    """El mínimo se alcanza justo o se supera: ambos casos se admiten."""
    check_minimum(total=10_000, minimum=10_000)
    check_minimum(total=25_000, minimum=10_000)


def test_dentro_del_horario_de_cocina_incluidos_los_extremos() -> None:
    """Apertura y cierre inclusive: a las 11:00 y a las 15:00 sigue habiendo cocina."""
    assert within_kitchen_hours(now=datetime(2026, 3, 2, 11, 0), schedule=(COCINA_LUNES,))
    assert within_kitchen_hours(now=datetime(2026, 3, 2, 13, 30), schedule=(COCINA_LUNES,))
    assert within_kitchen_hours(now=datetime(2026, 3, 2, 15, 0), schedule=(COCINA_LUNES,))


def test_fuera_del_horario_de_cocina_no_esta_dentro() -> None:
    """Antes de la apertura o después del cierre no se toma el pedido (regla 6)."""
    assert not within_kitchen_hours(now=datetime(2026, 3, 2, 10, 59), schedule=(COCINA_LUNES,))
    assert not within_kitchen_hours(now=datetime(2026, 3, 2, 15, 1), schedule=(COCINA_LUNES,))


def test_un_dia_sin_franja_nunca_esta_dentro() -> None:
    """Martes sin franja de cocina: nunca hay cocina aunque sea hora de comida."""
    assert not within_kitchen_hours(now=datetime(2026, 3, 3, 12, 0), schedule=(COCINA_LUNES,))


def test_sin_horario_inyectado_no_esta_dentro() -> None:
    """Sin horario (composición vacía) no se promete cocina abierta."""
    assert not within_kitchen_hours(now=LUNES_2026_03_02, schedule=())
