"""Tests de contrato HTTP de la consola local (FastAPI + TestClient)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from handlers.console_api import create_app
from handlers.console_fake_llm import FakeLLM
from handlers.console_runtime import ConsoleRuntime
from slices.tenant_prompts.application.service import TenantConfigService
from slices.tenant_prompts.domain.entities import DEFAULT_TENANT_ID, default_profile
from slices.tenant_prompts.infrastructure.local_json import LocalJsonTenantRepository


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Cliente HTTP con JSON temporal, LLM simulado y sin AWS."""
    repo = LocalJsonTenantRepository(tmp_path / "tenants.json", seed=default_profile())
    service = TenantConfigService(repository=repo)
    runtime = ConsoleRuntime(service=service, llm=FakeLLM(), llm_mode="fake")
    return TestClient(create_app(service=service, runtime=runtime))


def test_health_expone_el_modo_local(client: TestClient) -> None:
    respuesta = client.get("/api/health")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["status"] == "ok"
    assert datos["environment"] == "local"
    assert datos["llm_mode"] == "fake"


def test_lista_y_obtiene_el_comercio(client: TestClient) -> None:
    lista = client.get("/api/tenants")
    assert lista.status_code == 200
    assert lista.json()[0]["tenant_id"] == DEFAULT_TENANT_ID

    detalle = client.get(f"/api/tenants/{DEFAULT_TENANT_ID}")
    assert detalle.status_code == 200
    assert detalle.json()["display_name"] == "Sede Elite"


def test_comercio_desconocido_da_404(client: TestClient) -> None:
    respuesta = client.get("/api/tenants/No_Existe")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"] == "tenant_profile_not_found"


def test_actualiza_el_perfil(client: TestClient) -> None:
    respuesta = client.put(
        f"/api/tenants/{DEFAULT_TENANT_ID}", json={"display_name": "Café Central"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["display_name"] == "Café Central"
    assert client.get(f"/api/tenants/{DEFAULT_TENANT_ID}").json()["display_name"] == (
        "Café Central"
    )


def test_lista_y_edita_prompts(client: TestClient) -> None:
    lista = client.get(f"/api/tenants/{DEFAULT_TENANT_ID}/prompts")
    assert lista.status_code == 200
    assert {p["kind"] for p in lista.json()} == {
        "supervisor",
        "appointments",
        "orders",
        "faq",
    }

    base = client.get(f"/api/tenants/{DEFAULT_TENANT_ID}/prompts/supervisor")
    assert base.status_code == 200
    assert base.json()["is_override"] is False

    guardado = client.put(
        f"/api/tenants/{DEFAULT_TENANT_ID}/prompts/supervisor",
        json={"content": "PROMPT PROPIO"},
    )
    assert guardado.status_code == 200
    assert guardado.json()["is_override"] is True
    assert guardado.json()["content"] == "PROMPT PROPIO"

    restaurado = client.delete(f"/api/tenants/{DEFAULT_TENANT_ID}/prompts/supervisor")
    assert restaurado.status_code == 200
    assert restaurado.json()["is_override"] is False


def test_prompt_vacio_da_400(client: TestClient) -> None:
    respuesta = client.put(
        f"/api/tenants/{DEFAULT_TENANT_ID}/prompts/orders",
        json={"content": "   "},
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["error"] == "prompt_override_invalid"


def test_tipo_de_prompt_invalido_da_422(client: TestClient) -> None:
    respuesta = client.get(f"/api/tenants/{DEFAULT_TENANT_ID}/prompts/sales")
    assert respuesta.status_code == 422


def test_chat_reset_y_estado(client: TestClient) -> None:
    respuesta = client.post(
        "/api/chat",
        json={
            "tenant_id": DEFAULT_TENANT_ID,
            "session_id": "s1",
            "message": "hola",
        },
    )
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert "Sede Elite" in datos["reply"]
    assert datos["llm_mode"] == "fake"
    assert datos["thread_id"] == f"{DEFAULT_TENANT_ID}#console:s1"

    estado = client.get(f"/api/tenants/{DEFAULT_TENANT_ID}/state")
    assert estado.status_code == 200
    assert estado.json() == {"citas": 0, "pedidos": 0}

    reset = client.post(
        "/api/chat/reset",
        json={"tenant_id": DEFAULT_TENANT_ID, "session_id": "s1"},
    )
    assert reset.status_code == 200
    assert reset.json() == {"ok": True}
