"""Tests del runtime de la consola: saludo, overrides, entitlements y sesiones."""

from pathlib import Path

import pytest

from handlers.console_fake_llm import FakeLLM
from handlers.console_runtime import ConsoleRuntime
from shared.errors import ValidationError
from slices.tenant_prompts.application.service import TenantConfigService
from slices.tenant_prompts.domain.entities import (
    DEFAULT_TENANT_ID,
    TenantProfile,
    TenantProfileUpdate,
    default_profile,
)
from slices.tenant_prompts.infrastructure.local_json import LocalJsonTenantRepository


def _runtime(tmp_path: Path) -> tuple[ConsoleRuntime, FakeLLM, TenantConfigService]:
    """Compone un runtime aislado con LLM simulado y JSON temporal."""
    repo = LocalJsonTenantRepository(tmp_path / "tenants.json", seed=default_profile())
    service = TenantConfigService(repository=repo)
    llm = FakeLLM()
    runtime = ConsoleRuntime(service=service, llm=llm, llm_mode="fake")
    return runtime, llm, service


def test_el_saludo_usa_el_nombre_comercial(tmp_path: Path) -> None:
    runtime, _, service = _runtime(tmp_path)
    service.update_tenant(DEFAULT_TENANT_ID, TenantProfileUpdate(display_name="Café Central"))
    salida = runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="hola")
    assert salida.reply is not None
    assert "Café Central" in salida.reply
    assert salida.intent == "greeting"
    assert salida.target == "supervisor"


def test_el_override_del_supervisor_llega_al_llm(tmp_path: Path) -> None:
    runtime, llm, service = _runtime(tmp_path)
    service.update_prompt(DEFAULT_TENANT_ID, "supervisor", "PROMPT SUPERVISOR PROPIO")
    runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="hola")
    assert "PROMPT SUPERVISOR PROPIO" in (llm.last_system or "")


def test_el_override_del_especialista_llega_al_llm(tmp_path: Path) -> None:
    runtime, llm, service = _runtime(tmp_path)
    service.update_prompt(DEFAULT_TENANT_ID, "appointments", "PROMPT CITAS PROPIO")
    salida = runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="quiero una cita")
    assert salida.intent == "appointments"
    assert "PROMPT CITAS PROPIO" in (llm.last_system or "")


def test_el_override_de_faq_llega_al_llm(tmp_path: Path) -> None:
    runtime, llm, service = _runtime(tmp_path)
    service.update_prompt(DEFAULT_TENANT_ID, "faq", "PROMPT FAQ PROPIO")
    salida = runtime.chat(
        tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="cual es el horario"
    )
    assert salida.intent == "faq"
    assert salida.reply is not None
    assert "PROMPT FAQ PROPIO" in (llm.last_system or "")


def test_allowed_bots_restringe_el_enrutado(tmp_path: Path) -> None:
    runtime, _, service = _runtime(tmp_path)
    service.update_tenant(DEFAULT_TENANT_ID, TenantProfileUpdate(allowed_bots=frozenset({"faq"})))
    salida = runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="quiero una cita")
    assert salida.route_error == "intent_not_allowed"
    assert salida.target is None
    assert salida.reply is not None
    assert "no está disponible" in salida.reply


def test_sesiones_aisladas_y_reset(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)
    runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="hola")
    runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s2", message="hola")
    tenant = runtime.get(DEFAULT_TENANT_ID)
    assert len(tenant.histories) == 2

    runtime.reset(tenant_id=DEFAULT_TENANT_ID, session_id="s1")
    tenant = runtime.get(DEFAULT_TENANT_ID)
    assert len(tenant.histories) == 1
    assert f"{DEFAULT_TENANT_ID}#console:s2" in tenant.histories


def test_comercios_aislados(tmp_path: Path) -> None:
    repo = LocalJsonTenantRepository(tmp_path / "tenants.json", seed=default_profile())
    repo.save(TenantProfile(tenant_id="Otro_Comercio", display_name="Otro Comercio"))
    service = TenantConfigService(repository=repo)
    runtime = ConsoleRuntime(service=service, llm=FakeLLM(), llm_mode="fake")

    primero = runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="hola")
    segundo = runtime.chat(tenant_id="Otro_Comercio", session_id="s1", message="hola")
    assert "Sede Elite" in (primero.reply or "")
    assert "Otro Comercio" in (segundo.reply or "")
    assert (
        runtime.get(DEFAULT_TENANT_ID).appointments is not runtime.get("Otro_Comercio").appointments
    )


def test_reset_rechaza_sesion_con_separador(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)
    with pytest.raises(ValidationError):
        runtime.reset(tenant_id=DEFAULT_TENANT_ID, session_id="a#b")


def test_chat_rechaza_mensaje_vacio(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)
    with pytest.raises(ValidationError):
        runtime.chat(tenant_id=DEFAULT_TENANT_ID, session_id="s1", message="   ")
