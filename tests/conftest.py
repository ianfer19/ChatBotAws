"""Fixtures compartidas de la suite de tests.

Ahora (Paso 2) fija un `CHATBOT_BEDROCK_MODEL_ID` sintético para que los tests de
configuración puedan construir `Settings()` sin depender del entorno del desarrollador;
si el entorno ya trae uno real (p. ej. al correr el smoke test del Paso 2), se respeta.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _model_id_de_bedrock_de_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza `CHATBOT_BEDROCK_MODEL_ID` en el entorno sin pisar un valor real.

    Args:
        monkeypatch: Fixture de pytest para variables de entorno del test actual.

    Returns:
        None; el efecto es la variable de entorno disponible para todo el test.
    """
    if "CHATBOT_BEDROCK_MODEL_ID" not in os.environ:
        monkeypatch.setenv("CHATBOT_BEDROCK_MODEL_ID", "modelo-sintetico-de-test")
