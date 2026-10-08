"""Smoke real del grafo de citas (Paso 3): LangGraph + `BedrockLLM` contra Bedrock.

Ejecuta un turno de saludo con las dependencias de producción (modelo real,
repositorio en memoria, horario demo) para verificar el camino completo
`understand` → `validate` → `select_action` → `respond`. Son dos llamadas al modelo
por turno `TODO(verify pricing)` (Paso 14).

Se omite en CI o sin `CHATBOT_BEDROCK_MODEL_ID` real; si la cuenta aún no tiene
verificado el acceso a Bedrock, se omite con ese motivo en vez de fallar.
"""

from datetime import datetime

import pytest
from _aws import (  # pyrefly: ignore[missing-import]
    MODELO_BEDROCK,
    es_acceso_pendiente,
    hay_credenciales,
)
from botocore.exceptions import NoRegionError

from adapters.bedrock import BedrockLLM
from shared.config import load_settings
from shared.errors import ToolError
from slices.appointments.application.graph import build_appointment_graph
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not MODELO_BEDROCK, reason="sin CHATBOT_BEDROCK_MODEL_ID real en el entorno"
    ),
    pytest.mark.skipif(
        not hay_credenciales(), reason="sin credenciales AWS: el smoke test se omite en CI"
    ),
]

_TENANT = "Sede_Elite_01"
_HORARIO = (OpeningHoursDay(weekday=0, open_time="09:00", close_time="18:00"),)


class _RelojFijo:
    """Reloj fijo para que la disponibilidad del smoke sea estable."""

    def now(self) -> datetime:
        """Instante fijo del smoke (lunes 2026-03-02, 08:00 local naive).

        Returns:
            La hora fija configurada.
        """
        return datetime(2026, 3, 2, 8, 0)


def test_grafo_de_citas_responde_un_saludo_con_bedrock() -> None:
    """El grafo completo con el modelo real produce una respuesta no vacía."""
    settings = load_settings()
    try:
        llm = BedrockLLM(
            model_id=settings.bedrock_model_id,
            timeout_seconds=settings.bedrock_timeout_seconds,
        )
    except NoRegionError:
        pytest.skip("sin región de AWS: define AWS_DEFAULT_REGION (p. ej. us-east-1)")

    grafo = build_appointment_graph(
        llm=llm,
        repo=InMemoryAppointmentRepository(),
        clock=_RelojFijo(),
        opening_hours=_HORARIO,
    )
    try:
        estado = grafo.invoke(
            {
                "tenant_id": _TENANT,
                "correlation_id": "smoke-paso-3",
                "user_message": "hola",
            }
        )
    except ToolError as exc:
        if es_acceso_pendiente(exc):
            pytest.skip("la cuenta AWS aún no tiene verificado el acceso a modelos de Bedrock")
        raise

    reply = estado.get("reply")
    assert isinstance(reply, str)
    assert reply.strip()
