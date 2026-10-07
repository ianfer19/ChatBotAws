"""Tests del kernel: excepciones tipadas con código estable (shared/errors)."""

from shared.errors import (
    AppError,
    TenantError,
    TenantNotFoundError,
    ToolError,
    ToolTimeoutError,
    ValidationError,
)


def test_codigos_y_estatus_son_estables() -> None:
    """Cada error expone un `code` y un `http_status` estables para contratos y tests."""
    assert AppError.code == "app_error"
    assert AppError.http_status == 500
    assert ValidationError.code == "validation_error"
    assert ValidationError.http_status == 400
    assert TenantError.code == "tenant_error"
    assert TenantNotFoundError.code == "tenant_not_found"
    assert ToolError.code == "tool_error"
    assert ToolTimeoutError.code == "tool_timeout"


def test_jerarquia_de_errores() -> None:
    """Los errores concretos heredan de sus categorías y de `AppError`."""
    error = TenantNotFoundError("sin mapeo")
    assert isinstance(error, TenantError)
    assert isinstance(error, AppError)
    assert isinstance(error, Exception)


def test_to_dict_no_expone_trazas_ni_especial_de_python() -> None:
    """La representación para log/respuesta es un dict estable, sin stack trace."""
    error = ToolError("timeout del legacy", details={"tool": "get_menu"})
    assert error.to_dict() == {
        "error": "tool_error",
        "message": "timeout del legacy",
        "details": {"tool": "get_menu"},
    }
    assert "Traceback" not in str(error.to_dict())


def test_details_por_defecto_es_dict_vacio() -> None:
    """Sin `details`, el error sigue siendo representable (nunca `None`)."""
    error = ValidationError("payload inválido")
    assert error.details == {}
    assert error.to_dict()["details"] == {}
