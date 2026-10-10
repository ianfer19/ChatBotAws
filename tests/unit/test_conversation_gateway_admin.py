"""Tests del endpoint admin del gateway (Fase 5): alta de canal con token propio.

Cubre las tres capas: modelo del cuerpo (forma estricta), caso de uso (orden
mapeo→credenciales) y handler (token en tiempo constante, método, traducción de
errores). Sin AWS: dobles en memoria y receptor inyectado.
"""

import json

import pytest
from pydantic import ValidationError as ValidationErrorPydantic

from shared.contracts.types import Channel
from shared.errors import ToolError, ValidationError
from slices.conversation_gateway.application.admin import AdminChannelRequest, AdminChannelsUseCase
from slices.conversation_gateway.domain.ports import (
    ChannelMappingWriterPort,
    CredentialsPort,
)
from slices.conversation_gateway.handler import lambda_admin
from slices.conversation_gateway.infrastructure.in_memory import (
    InMemoryCredentialStore,
    InMemoryTenantResolver,
)

_TOKEN = "token-admin-de-prueba"
_TENANT = "Sede_Elite_01"
_CUERPO_OK: dict[str, str] = {
    "channel": "whatsapp",
    "emitter_id": "1000",
    "tenant_id": _TENANT,
    "access_token": "tok-canal",
}


def _caso() -> tuple[AdminChannelsUseCase, InMemoryTenantResolver, InMemoryCredentialStore]:
    """Caso de uso con dobles en memoria.

    Returns:
        El caso de uso y sus dobles (para inspeccionar mapeo y credenciales).
    """
    resolver = InMemoryTenantResolver()
    store = InMemoryCredentialStore()
    return AdminChannelsUseCase(mapping=resolver, credentials=store), resolver, store


def _entorno_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija el entorno mínimo de la Lambda admin (modelo + token)."""
    monkeypatch.setenv("CHATBOT_BEDROCK_MODEL_ID", "modelo-de-prueba")
    monkeypatch.setenv("CHATBOT_ADMIN_TOKEN", _TOKEN)


def _evento_post(
    cuerpo: dict[str, object] | str | None = None,
    *,
    token: str | None = _TOKEN,
    metodo: str = "POST",
) -> dict[str, object]:
    """Evento mínimo de API Gateway para el admin.

    Args:
        cuerpo: Dict o texto crudo del `rawBody` (por defecto, un alta válida).
        token: Valor del header `x-admin-token` (`None` = header ausente).
        metodo: Método HTTP del evento.

    Returns:
        El payload 2.0 con `requestContext`, `headers` y `rawBody`.
    """
    if cuerpo is None:
        cuerpo = dict(_CUERPO_OK)
    cuerpo_texto = cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo)
    return {
        "requestContext": {"http": {"method": metodo}},
        "headers": {"x-admin-token": token} if token is not None else {},
        "rawBody": cuerpo_texto,
    }


# --- modelo del cuerpo -----------------------------------------------------------------------


def test_modelo_acepta_un_alta_completa() -> None:
    """El cuerpo válido pasa con canal tipado y secretos opcionales."""
    request = AdminChannelRequest.model_validate_json(json.dumps(_CUERPO_OK))
    assert (request.channel, request.emitter_id, request.tenant_id) == (
        "whatsapp",
        "1000",
        _TENANT,
    )


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"channel": "telegram", "emitter_id": "1", "tenant_id": _TENANT},
        {"channel": "whatsapp", "emitter_id": "", "tenant_id": _TENANT},
        {"channel": "whatsapp", "emitter_id": "1", "tenant_id": ""},
        {"channel": "whatsapp", "emitter_id": "1", "tenant_id": _TENANT, "access_token": ""},
        {"channel": "whatsapp", "emitter_id": "1", "tenant_id": _TENANT, "sobra": "x"},
        {"channel": "whatsapp"},
    ],
)
def test_modelo_rechaza_cuerpos_invalidos(cuerpo: dict[str, object]) -> None:
    """Canal fuera de los 3, ids vacíos, token en blanco o campos de sobra."""
    with pytest.raises(ValidationErrorPydantic):
        AdminChannelRequest.model_validate_json(json.dumps(cuerpo))


# --- caso de uso -----------------------------------------------------------------------------


def test_registra_mapeo_y_credenciales() -> None:
    """El alta escribe el mapeo y los dos secretos en sus stores."""
    caso, resolver, store = _caso()
    caso.register_channel(
        AdminChannelRequest.model_validate_json(json.dumps({**_CUERPO_OK, "app_secret": "shh"}))
    )
    assert resolver.resolve(channel="whatsapp", emitter_id="1000") == _TENANT
    assert store.get_access_token(channel="whatsapp", tenant_id=_TENANT) == "tok-canal"


def test_registra_solo_el_mapeo_si_no_vienen_secretos() -> None:
    """El token es opcional: el alta del mapeo no depende de tener credenciales aún."""
    caso, resolver, _store = _caso()
    caso.register_channel(
        AdminChannelRequest.model_validate_json(
            json.dumps({"channel": "instagram", "emitter_id": "PAGE_1", "tenant_id": _TENANT})
        )
    )
    assert resolver.resolve(channel="instagram", emitter_id="PAGE_1") == _TENANT


def test_si_el_mapeo_falla_no_se_escriben_las_credenciales() -> None:
    """Orden defensivo: sin mapeo no hay comercio, y el secret no queda huérfano."""
    store = InMemoryCredentialStore()
    caso = AdminChannelsUseCase(mapping=_MappingRoto(), credentials=store)
    with pytest.raises(ToolError):
        caso.register_channel(AdminChannelRequest.model_validate_json(json.dumps(_CUERPO_OK)))
    assert store._secretos == {}


class _MappingRoto:
    """Doble de mapping que falla como DynamoDB caído."""

    def register(self, *, channel: Channel, emitter_id: str, tenant_id: str) -> None:
        """Siempre falla (el caso de uso no debe continuar).

        Args:
            channel: Canal (ignorado).
            emitter_id: Emisor (ignorado).
            tenant_id: Comercio (ignorado).

        Raises:
            ToolError: El fallo inyectado.
        """
        del channel, emitter_id, tenant_id
        raise ToolError("dynamo caido")


# --- handler ---------------------------------------------------------------------------------


def test_handler_registra_y_responde_201(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST con token correcto: 201 y el estado queda en los dobles."""
    _entorno_admin(monkeypatch)
    caso, resolver, _store = _caso()
    respuesta = lambda_admin.main(_evento_post(), None, caso=caso)
    assert respuesta["statusCode"] == 201
    assert json.loads(respuesta["body"]) == {"ok": True}
    assert resolver.resolve(channel="whatsapp", emitter_id="1000") == _TENANT


@pytest.mark.parametrize(
    ("token", "cuerpo"),
    [(None, _CUERPO_OK), ("token-malo", _CUERPO_OK)],
)
def test_handler_sin_token_correcto_es_401(
    monkeypatch: pytest.MonkeyPatch, *, token: str | None, cuerpo: dict[str, object]
) -> None:
    """Header ausente o token erróneo: 401 sin distinguir el motivo."""
    _entorno_admin(monkeypatch)
    caso, _resolver, _store = _caso()
    respuesta = lambda_admin.main(_evento_post(cuerpo, token=token), None, caso=caso)
    assert respuesta["statusCode"] == 401
    assert json.loads(respuesta["body"]) == {"error": "unauthorized"}


def test_handler_rechaza_metodos_distintos_de_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo `POST`: GET/PUT/DELETE responden 405 sin tocar el caso de uso."""
    _entorno_admin(monkeypatch)
    caso, _resolver, _store = _caso()
    for metodo in ("GET", "PUT", "DELETE"):
        respuesta = lambda_admin.main(_evento_post(metodo=metodo), None, caso=caso)
        assert respuesta["statusCode"] == 405
        assert json.loads(respuesta["body"]) == {"error": "method_not_allowed"}


@pytest.mark.parametrize(
    "cuerpo",
    ["no-es-json", {"channel": "telegram", "emitter_id": "1", "tenant_id": _TENANT}, {}],
)
def test_handler_cuerpo_invalido_es_400(
    monkeypatch: pytest.MonkeyPatch, *, cuerpo: dict[str, object] | str
) -> None:
    """JSON roto, canal desconocido o cuerpo vacío: 400 con el código estable."""
    _entorno_admin(monkeypatch)
    caso, _resolver, _store = _caso()
    respuesta = lambda_admin.main(_evento_post(cuerpo), None, caso=caso)
    assert respuesta["statusCode"] == 400
    assert json.loads(respuesta["body"]) == {"error": "validation_error"}


def test_handler_traduce_errores_de_servicio_a_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si DynamoDB/SSM fallan, el cliente ve 502 sin trazas ni detalles."""
    _entorno_admin(monkeypatch)
    caso, _resolver, _store = _caso()
    caso._mapping = _MappingRoto()
    respuesta = lambda_admin.main(_evento_post(), None, caso=caso)
    assert respuesta["statusCode"] == 502
    assert json.loads(respuesta["body"]) == {"error": "tool_error"}
    assert "dynamo" not in respuesta["body"].lower()


def test_handler_falla_al_arrancar_sin_ajustes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin `CHATBOT_ADMIN_TOKEN` no hay composición posible (fail fast, no 401)."""
    monkeypatch.setenv("CHATBOT_BEDROCK_MODEL_ID", "modelo-de-prueba")
    monkeypatch.delenv("CHATBOT_ADMIN_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        lambda_admin.main(_evento_post(), None)


def test_handler_no_filtra_el_token_en_las_respuestas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ningún cuerpo de error contiene el token configurado ni el recibido."""
    _entorno_admin(monkeypatch)
    caso, _resolver, _store = _caso()
    respuesta = lambda_admin.main(_evento_post(token="intento-fallido"), None, caso=caso)
    assert "intento-fallido" not in respuesta["body"]
    assert _TOKEN not in respuesta["body"]


def test_dobles_cumplen_los_ports_del_dominio() -> None:
    """Los dobles del slice siguen satisfaciendo los ports (DI estructural)."""
    assert isinstance(InMemoryTenantResolver(), ChannelMappingWriterPort)
    assert isinstance(InMemoryCredentialStore(), CredentialsPort)
