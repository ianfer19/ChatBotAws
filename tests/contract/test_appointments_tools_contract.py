"""Contrato de las tools de citas: esquemas y firmas que consumen otros slices (Paso 5).

Frontera pública de `appointments`: lo que se verifica aquí no puede romperse sin avisar
a los emisores/receptores (AGENTS.md raíz, §9). En particular, el `tenant_id` jamás entra
por el payload del LLM: solo como argumento explícito del contexto resuelto en el gateway.
"""

import inspect
from collections.abc import Callable

import pytest
from pydantic import ValidationError as SchemaValidationError

from slices.appointments.application.schemas import AppointmentProposal, ToolResult
from slices.appointments.application.tools import AppointmentTools

pytestmark = pytest.mark.contract

_MINIMA = {
    "action": "propose_appointment",
    "date": "2026-03-02",
    "time": "10:00",
    "customer_name": "Ana Pérez",
    "contact": "3001112233",
}


def test_la_propuesta_no_admite_el_tenant_ni_claves_ajenas() -> None:
    """Un `tenant_id` (u otra clave de más) en el JSON del LLM invalida la propuesta."""
    with pytest.raises(SchemaValidationError):
        AppointmentProposal.model_validate({**_MINIMA, "tenant_id": "Comercio_Ajeno_99"})
    assert "tenant_id" not in AppointmentProposal.model_fields


def test_el_resultado_de_tool_es_inmutable_y_sin_campos_ajenos() -> None:
    """El `ToolResult` no admite cambios laterales ni campos fuera del esquema."""
    resultado = ToolResult(tool="propose_appointment")
    with pytest.raises(SchemaValidationError):
        resultado.draft_id = "drf-ajeno"  # pyrefly: ignore[read-only]
    with pytest.raises(SchemaValidationError):
        ToolResult.model_validate({"tool": "propose_appointment", "tenant_id": "x"})


def test_las_tools_de_escritura_solo_admiten_argumentos_nombrados() -> None:
    """Sin `*args`/`**kwargs` y todos anotados: imposible colar argumentos por sorpresa."""
    esperados: list[tuple[Callable[..., ToolResult], set[str]]] = [
        (
            AppointmentTools.propose_appointment,
            {
                "tenant_id",
                "correlation_id",
                "conversation_id",
                "message",
                "date",
                "time",
                "customer_name",
                "contact",
            },
        ),
        (
            AppointmentTools.cancel_appointment,
            {
                "tenant_id",
                "correlation_id",
                "conversation_id",
                "message",
                "appointment_id",
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
