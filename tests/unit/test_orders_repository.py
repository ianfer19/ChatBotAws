"""Tests del repositorio de pedidos en memoria (doble del Paso 1) y de sus entidades."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from shared.errors import ValidationError
from slices.orders.domain.entities import Order, OrderItem
from slices.orders.domain.ports import OrderRepositoryPort
from slices.orders.infrastructure.in_memory import InMemoryOrderRepository

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Otro_Comercio_01"
AHORA = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _pedido(
    order_id: str = "o-1",
    *,
    tenant_id: str = TENANT,
    correlation_id: str | None = "corr-1",
) -> Order:
    """Construye un pedido sintético de prueba (sin lógica de negocio).

    Args:
        order_id: Identificador del pedido.
        tenant_id: Comercio dueño del pedido.
        correlation_id: Clave de idempotencia de la creación.

    Returns:
        Pedido ya validado por el modelo.
    """
    return Order(
        id=order_id,
        tenant_id=tenant_id,
        items=(OrderItem(sku="PEPPERONI-1", quantity=2),),
        status="ABIERTA",
        created_at=AHORA,
        correlation_id=correlation_id,
    )


def test_doble_cumple_el_puerto_del_dominio() -> None:
    """mypy y `isinstance` confirman que el doble implementa `OrderRepositoryPort`."""
    repo: OrderRepositoryPort = InMemoryOrderRepository()
    assert isinstance(repo, OrderRepositoryPort)


def test_guardar_y_buscar_un_pedido() -> None:
    """El ciclo básico del repositorio devuelve exactamente lo guardado."""
    repo = InMemoryOrderRepository()
    pedido = _pedido()
    repo.save(tenant_id=TENANT, order=pedido)
    assert repo.find(tenant_id=TENANT, order_id="o-1") == pedido


def test_un_pedido_de_otro_comercio_es_inexistente() -> None:
    """Un pedido ajeno no se consulta: se reporta como inexistente, nunca como ajeno."""
    repo = InMemoryOrderRepository()
    repo.save(tenant_id=TENANT, order=_pedido())
    assert repo.find(tenant_id=OTRO_TENANT, order_id="o-1") is None


def test_no_se_puede_guardar_un_pedido_ajeno_al_tenant() -> None:
    """El tenant de la entidad y el del contexto deben coincidir (defensa en profundidad)."""
    repo = InMemoryOrderRepository()
    with pytest.raises(ValidationError):
        repo.save(tenant_id=OTRO_TENANT, order=_pedido(tenant_id=TENANT))


def test_sin_tenant_no_se_ejecuta_ninguna_operacion() -> None:
    """Un `tenant_id` vacío es un bug de composición y se rechaza de inmediato."""
    repo = InMemoryOrderRepository()
    with pytest.raises(ValidationError):
        repo.find(tenant_id="", order_id="o-1")
    with pytest.raises(ValidationError):
        repo.save(tenant_id="", order=_pedido())


def test_idempotencia_por_correlation_id() -> None:
    """Reintentar la misma creación devuelve el pedido ya guardado, sin duplicar."""
    repo = InMemoryOrderRepository()
    repo.save(tenant_id=TENANT, order=_pedido(correlation_id="corr-7"))
    encontrado = repo.find_by_correlation_id(tenant_id=TENANT, correlation_id="corr-7")
    assert encontrado is not None and encontrado.id == "o-1"
    assert repo.find_by_correlation_id(tenant_id=OTRO_TENANT, correlation_id="corr-7") is None


def test_order_no_expone_la_hora_del_pedido() -> None:
    """Capa 2 de la defensa en profundidad (AGENTS raíz §7): el dominio no tiene la hora.

    Si algún campo con ese significado aparecera en `Order`, el chatbot podría
    manipularla desde el dominio y esta regresión fallaría.
    """
    nombres_de_campo = set(Order.model_fields)
    assert not any("hora" in nombre or "time" in nombre for nombre in nombres_de_campo)
    assert Order.model_config.get("frozen") is True


def test_linea_de_pedido_con_cantidad_no_positiva_es_invalida() -> None:
    """Cantidades cero o negativas no llegan ni al repositorio."""
    with pytest.raises(PydanticValidationError):
        OrderItem.model_validate({"sku": "PEPPERONI-1", "quantity": 0})


def test_entidad_inmutable_y_sin_campos_ajenos() -> None:
    """El pedido ya guardado no admite cambios laterales ni campos no previstos."""
    pedido = _pedido()
    with pytest.raises(PydanticValidationError):
        pedido.status = "paid"  # type: ignore[assignment]  # pyrefly: ignore[read-only]
    with pytest.raises(PydanticValidationError):
        Order.model_validate({**pedido.model_dump(), "price": 50_000})
