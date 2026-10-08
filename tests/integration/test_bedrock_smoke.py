"""Smoke test real de Bedrock (Paso 2): Python → `BedrockLLM` → Converse → modelo → texto.

Corre solo con credenciales de dev y `CHATBOT_BEDROCK_MODEL_ID` real (en CI se omite);
usa la Converse API con una respuesta mínima, así el coste por ejecución es despreciable
`TODO(verify pricing)` (Paso 14).

Si la cuenta aún no tiene verificado el acceso a modelos de Bedrock, el test se omite con
el motivo en vez de fallar: no es un bug del código sino un estado de la cuenta AWS.
"""

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
from shared.ports import LLMMessage, LLMPort

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not MODELO_BEDROCK, reason="sin CHATBOT_BEDROCK_MODEL_ID real en el entorno"
    ),
    pytest.mark.skipif(
        not hay_credenciales(), reason="sin credenciales AWS: el smoke test se omite en CI"
    ),
]


def test_llm_de_bedrock_responde_a_un_mensaje() -> None:
    """`BedrockLLM` + `Settings` producen una respuesta real del modelo en Bedrock."""
    settings = load_settings()
    try:
        llm = BedrockLLM(
            model_id=settings.bedrock_model_id, timeout_seconds=settings.bedrock_timeout_seconds
        )
    except NoRegionError:
        pytest.skip("sin región de AWS: define AWS_REGION (p. ej. us-east-1)")
    assert isinstance(llm, LLMPort)

    try:
        resultado = llm.invoke(
            messages=[LLMMessage(role="user", content="Responde únicamente con OK")],
            system="Eres un asistente de prueba.",
            max_tokens=16,
        )
    except ToolError as exc:
        if es_acceso_pendiente(exc):
            pytest.skip("la cuenta AWS aún no tiene verificado el acceso a modelos de Bedrock")
        raise

    assert resultado.text.strip()
    assert resultado.input_tokens is not None and resultado.input_tokens >= 0
    assert resultado.output_tokens is not None and resultado.output_tokens >= 0
