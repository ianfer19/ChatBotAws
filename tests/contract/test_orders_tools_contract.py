"""Contrato de las tools de pedidos: esquemas y firmas que consumen otros slices (Paso 5).

Frontera pública de `orders`: lo que se verifica aquí no puede romperse sin avisar a los
emisores/receptores (AGENTS.md raíz, §9). En particular, el `tenant_id` jamás entra por
el payload del LLM y ningún campo de hora del pedido existe en el esquema (defensa en
profundidad de la regla crítica, AGENTS §7).
"""

import inspect
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError as SchemaValidationError

from slices.orders.application.schemas import OrderProposal, ToolResult
from slices.orders.application.tools import OrderTools

pytestmark = pytest.mark.contract

_MINIMA: dict[str, Any] = {
    "action": "propose_order",
    "items": [{"sku": "A-100", "quantity": 2}],
}


def test_la_propuesta_no_admite_el_tenant_ni_claves_ajenas() -> None:
    """Un `tenant_id` (u otra clave de más) en el JSON del LLM invalida la propuesta."""
    with pytest.raises(SchemaValidationError):
        OrderProposal.model_validate({**_MINIMA, "tenant_id": "Comercio_Ajeno_99"})
    assert "tenant_id" not in OrderProposal.model_fields


def test_la_propuesta_no_admite_ningun_campo_de_hora_del_pedido() -> None:
    """Ninguna clave de horario entra en el esquema: la operación no existe (capa 1)."""
    for clave in ("scheduled_at", "scheduled_time", "hora", "date", "time"):
        with pytest.raises(SchemaValidationError):
            OrderProposal.model_validate({**_MINIMA, clave: "2026-03-02T10:00"})
        assert clave not in OrderProposal.model_fields


def test_los_items_tampoco_admiten_claves_de_hora() -> None:
    """Ni dentro de cada línea del carrito se cuela un campo de hora o precio."""
    with pytest.raises(SchemaValidationError):
        OrderProposal.model_validate(
            {"action": "propose_order", "items": [{"sku": "A-100", "quantity": 2, "hora": "10:00"}]}
        )
    with pytest.raises(SchemaValidationError):
        OrderProposal.model_validate(
            {
                "action": "propose_order",
                "items": [{"sku": "A-100", "quantity": 2, "price": 18_000}],
            }
        )


def test_el_resultado_de_tool_es_inmutable_y_sin_campos_ajenos() -> None:
    """El `ToolResult` no admite cambios laterales ni campos fuera del esquema."""
    resultado = ToolResult(tool="propose_order")
    with pytest.raises(SchemaValidationError):
        resultado.draft_id = "drf-ajeno"  # pyrefly: ignore[read-only]
    with pytest.raises(SchemaValidationError):
        ToolResult.model_validate({"tool": "propose_order", "tenant_id": "x"})


def test_las_tools_de_escritura_solo_admiten_argumentos_nombrados() -> None:
    """Sin `*args`/`**kwargs` y todos anotados: imposible colar argumentos por sorpresa."""
    esperados: list[tuple[Callable[..., ToolResult], set[str]]] = [
        (
            OrderTools.propose_order,
            {
                "tenant_id",
                "correlation_id",
                "conversation_id",
                "message",
                "items",
            },
        ),
    ]
    for metodo, requeridos in esperados:
        parametros = {
            nombre: parametro
            for nombre, parametro in inspect.signature(metodo).parameters.items()
            if nombre != "self"
        }
        assert set(parametros) == requeridos
        assert all(
            parametro.kind is inspect.Parameter.KEYWORD_ONLY for parametro in parametros.values()
        )
        assert all(
            parametro.annotation is not inspect.Parameter.empty for parametro in parametros.values()
        )
