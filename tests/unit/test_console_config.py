"""Tests del store local y de los casos de uso de perfil/prompt (Fase A)."""

from pathlib import Path

import pytest

from shared.errors import ValidationError
from slices.tenant_prompts.application.service import TenantConfigService
from slices.tenant_prompts.domain.entities import (
    DEFAULT_TENANT_ID,
    TenantProfile,
    TenantProfileUpdate,
    default_profile,
)
from slices.tenant_prompts.domain.errors import (
    PromptOverrideInvalidError,
    TenantProfileNotFoundError,
)
from slices.tenant_prompts.infrastructure.local_json import LocalJsonTenantRepository


def _servicio(tmp_path: Path) -> tuple[TenantConfigService, LocalJsonTenantRepository]:
    """Crea un servicio con un JSON temporal sembrado con el comercio demo."""
    repo = LocalJsonTenantRepository(tmp_path / "tenants.json", seed=default_profile())
    return TenantConfigService(repository=repo), repo


def test_siembra_y_lista_el_comercio_demo(tmp_path: Path) -> None:
    service, _ = _servicio(tmp_path)
    perfiles = service.list_tenants()
    assert [p.tenant_id for p in perfiles] == [DEFAULT_TENANT_ID]
    assert service.get_tenant(DEFAULT_TENANT_ID).display_name == "Sede Elite"


def test_actualiza_solo_los_campos_enviados(tmp_path: Path) -> None:
    service, _ = _servicio(tmp_path)
    actualizado = service.update_tenant(
        DEFAULT_TENANT_ID, TenantProfileUpdate(display_name="Café Central")
    )
    assert actualizado.display_name == "Café Central"
    assert actualizado.tone == "cercano"
    assert actualizado.allowed_bots == default_profile().allowed_bots


def test_la_configuracion_persiste_entre_instancias(tmp_path: Path) -> None:
    service, _ = _servicio(tmp_path)
    service.update_tenant(DEFAULT_TENANT_ID, TenantProfileUpdate(display_name="Café Central"))
    otro = TenantConfigService(repository=LocalJsonTenantRepository(tmp_path / "tenants.json"))
    assert otro.get_tenant(DEFAULT_TENANT_ID).display_name == "Café Central"


def test_prompt_override_y_reset(tmp_path: Path) -> None:
    service, _ = _servicio(tmp_path)
    base = service.get_prompt(DEFAULT_TENANT_ID, "supervisor")
    assert base.is_override is False
    assert base.content == base.base_content

    nuevo = service.update_prompt(DEFAULT_TENANT_ID, "supervisor", "PROMPT PROPIO")
    assert nuevo.is_override is True
    assert nuevo.content == "PROMPT PROPIO"

    restaurado = service.reset_prompt(DEFAULT_TENANT_ID, "supervisor")
    assert restaurado.is_override is False
    assert restaurado.content == base.base_content


def test_prompt_vacio_se_rechaza(tmp_path: Path) -> None:
    service, _ = _servicio(tmp_path)
    with pytest.raises(PromptOverrideInvalidError):
        service.update_prompt(DEFAULT_TENANT_ID, "orders", "   ")


def test_prompt_demasiado_largo_se_rechaza(tmp_path: Path) -> None:
    service, _ = _servicio(tmp_path)
    with pytest.raises(PromptOverrideInvalidError):
        service.update_prompt(DEFAULT_TENANT_ID, "faq", "x" * 50_001)


def test_tenant_desconocido(tmp_path: Path) -> None:
    service, _ = _servicio(tmp_path)
    with pytest.raises(TenantProfileNotFoundError):
        service.get_tenant("No_Existe")


def test_json_corrupto_da_error_tipado(tmp_path: Path) -> None:
    ruta = tmp_path / "tenants.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")
    repo = LocalJsonTenantRepository(ruta)
    with pytest.raises(ValidationError):
        repo.list()


def test_aislamiento_entre_comercios(tmp_path: Path) -> None:
    repo = LocalJsonTenantRepository(tmp_path / "tenants.json", seed=default_profile())
    otro = TenantProfile(tenant_id="Otro_Comercio", display_name="Otro Comercio")
    repo.save(otro)
    service = TenantConfigService(repository=repo)
    service.update_prompt(DEFAULT_TENANT_ID, "supervisor", "SOLO DEL PRIMERO")
    assert service.get_prompt(DEFAULT_TENANT_ID, "supervisor").is_override is True
    assert service.get_prompt("Otro_Comercio", "supervisor").is_override is False
