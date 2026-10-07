"""Tests del kernel: contexto de tenant/correlación con contextvars (shared/context)."""

import pytest

from shared.context import (
    TenantContext,
    bind_context,
    current_context,
    get_context,
    reset_context,
    set_context,
)
from shared.errors import ContextNotSetError


def _context(tenant_id: str = "Sede_Elite_01") -> TenantContext:
    """Contexto sintético de prueba."""
    return TenantContext(
        tenant_id=tenant_id,
        correlation_id="corr-test-0001",
        channel="whatsapp",
        customer_id="57300111111",
    )


def test_set_y_reset_recuperan_el_contexto_anterior() -> None:
    """`set_context` devuelve token y `reset_context` deja el contexto como estaba."""
    token = set_context(_context())
    try:
        assert get_context().tenant_id == "Sede_Elite_01"
        assert current_context() is not None
    finally:
        reset_context(token)
    assert current_context() is None


def test_get_context_sin_fijar_lanza_error_tipado() -> None:
    """La lógica de negocio exige contexto; sin él falla con `ContextNotSetError`."""
    assert current_context() is None
    with pytest.raises(ContextNotSetError):
        get_context()


def test_bind_context_limpia_al_salir_del_bloque() -> None:
    """El helper de composición fija el contexto y lo restablece siempre (DI ligera)."""
    with bind_context(_context()) as ctx:
        assert current_context() is ctx
    assert current_context() is None


def test_bind_context_anidado_restaura_el_contexto_externo() -> None:
    """Los bloques anidados restauran el contexto exterior (tokens de contextvar)."""
    with bind_context(_context("externo")):
        with bind_context(_context("interno")):
            assert get_context().tenant_id == "interno"
        assert get_context().tenant_id == "externo"
    assert current_context() is None


def test_contexto_es_inmutable() -> None:
    """El contexto no se muta en caliente: un turno nuevo crea uno nuevo."""
    context = _context()
    with pytest.raises(ValueError):
        context.tenant_id = "otro"
