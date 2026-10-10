"""Tests del webhook Meta (Fase 2): verificación GET, firma POST y handler Lambda."""

import base64
import hashlib
import hmac
import json
from typing import Any

import pytest

from shared.errors import ValidationError
from slices.conversation_gateway.application.webhook import WebhookReceiver
from slices.conversation_gateway.domain.errors import InvalidSignatureError
from slices.conversation_gateway.handler import lambda_webhook

_TOKEN = "token-de-verificacion"
_SECRETO = "app-secreta-del-test"
_PAYLOAD = b'{"object":"whatsapp_business_account","entry":[]}'


def _firma(cuerpo: bytes = _PAYLOAD) -> str:
    """Firma de prueba con el mismo algoritmo que Meta (HMAC-SHA256)."""
    return "sha256=" + hmac.new(_SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()


def _receptor() -> WebhookReceiver:
    """Receiver de prueba con los secretos fijos."""
    return WebhookReceiver(verify_token=_TOKEN, app_secret=_SECRETO)


def _entorno_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija las variables de entorno que la Lambda del webhook necesita para arrancar.

    Args:
        monkeypatch: Fixture de pytest para variables de entorno.
    """
    monkeypatch.setenv("CHATBOT_BEDROCK_MODEL_ID", "modelo-de-prueba")
    monkeypatch.setenv("CHATBOT_WEBHOOK_VERIFY_TOKEN", _TOKEN)
    monkeypatch.setenv("CHATBOT_META_APP_SECRET", _SECRETO)


def _evento_get(
    *, token: str | None = _TOKEN, challenge: str | None = "98765", mode: str | None = "subscribe"
) -> dict[str, Any]:
    """Evento API Gateway (payload 2.0) para el GET de verificación."""
    return {
        "version": "2.0",
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {
            "hub.mode": mode,
            "hub.verify_token": token,
            "hub.challenge": challenge,
        },
    }


def _evento_post(
    cuerpo: bytes = _PAYLOAD,
    *,
    firma: str | None = "auto",
    metodo: str = "POST",
) -> dict[str, Any]:
    """Evento API Gateway (payload 2.0) para el POST; la cabecera va en mayúsculas a propósito."""
    headers: dict[str, str] = {}
    if firma == "auto":
        headers["X-Hub-Signature-256"] = _firma(cuerpo)
    elif firma is not None:
        headers["X-Hub-Signature-256"] = firma
    return {
        "version": "2.0",
        "requestContext": {"http": {"method": metodo}},
        "headers": headers,
        "rawBody": cuerpo.decode("utf-8"),
        "isBase64Encoded": False,
    }


# --- WebhookReceiver: verificación GET ------------------------------------------------


def test_receptor_exige_los_secretos() -> None:
    """Sin verify_token o sin app_secret la Lambda no debe arrancar (fail fast)."""
    with pytest.raises(ValidationError):
        WebhookReceiver(verify_token="", app_secret=_SECRETO)
    with pytest.raises(ValidationError):
        WebhookReceiver(verify_token=_TOKEN, app_secret="")


def test_verificacion_correcta_devuelve_el_challenge() -> None:
    """Meta exige devolver `hub.challenge` tal cual con status 200."""
    respuesta = _receptor().verify_subscription(mode="subscribe", token=_TOKEN, challenge="12345")
    assert (respuesta.status, respuesta.body) == (200, "12345")


@pytest.mark.parametrize(
    ("mode", "token", "challenge"),
    [
        ("subscribe", "token-malo", "12345"),
        ("unsubscribe", _TOKEN, "12345"),
        ("subscribe", _TOKEN, None),
        ("subscribe", None, "12345"),
        (None, _TOKEN, "12345"),
    ],
)
def test_verificacion_invalida_es_403_sin_motivo(
    *, mode: str | None, token: str | None, challenge: str | None
) -> None:
    """Cualquier desajuste se rechaza con 403 genérico (sin decir qué falló)."""
    respuesta = _receptor().verify_subscription(mode=mode, token=token, challenge=challenge)
    assert respuesta.status == 403
    assert json.loads(respuesta.body) == {"error": "forbidden"}


# --- WebhookReceiver: firma POST ---------------------------------------------------------


def test_post_con_firma_valida_de_un_canal_meta_es_aceptado() -> None:
    """Firma correcta y envelope de un canal → 200 EVENT_RECEIVED."""
    respuesta = _receptor().receive(raw_body=_PAYLOAD, signature=_firma())
    assert (respuesta.status, respuesta.body) == (200, "EVENT_RECEIVED")


def test_post_sin_firma_o_firma_alterada_es_invalid_signature() -> None:
    """La firma es obligatoria en todo entorno (a diferencia del legacy comentado)."""
    with pytest.raises(InvalidSignatureError):
        _receptor().receive(raw_body=_PAYLOAD, signature=None)
    with pytest.raises(InvalidSignatureError):
        _receptor().receive(raw_body=_PAYLOAD, signature=_firma()[:-2] + "00")
    with pytest.raises(InvalidSignatureError):
        _receptor().receive(raw_body=_PAYLOAD + b" ", signature=_firma())


def test_post_firmado_de_envelope_desconocido_es_ignored() -> None:
    """Un envelope que no es de los 3 canales se acusa con 200 y no se procesa."""
    cuerpo = b'{"object":"unknown_platform"}'
    respuesta = _receptor().receive(
        raw_body=cuerpo,
        signature="sha256=" + hmac.new(_SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest(),
    )
    assert (respuesta.status, respuesta.body) == (200, "EVENT_IGNORED")


@pytest.mark.parametrize("cuerpo", [b"no-es-json", b'"cadena"', b"[1,2,3]", b""])
def test_post_firmado_con_cuerpo_no_objeto_es_validation_error(cuerpo: bytes) -> None:
    """Firma válida pero cuerpo que Meta nunca enviaría: se rechaza sin procesar."""
    firma = "sha256=" + hmac.new(_SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
    with pytest.raises(ValidationError):
        _receptor().receive(raw_body=cuerpo, signature=firma)


# --- handler main (API Gateway → respuesta) ----------------------------------------------


def test_handler_get_devuelve_el_challenge_en_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    """El GET de verificación responde 200 con el challenge en text/plain."""
    _entorno_webhook(monkeypatch)
    respuesta = lambda_webhook.main(_evento_get(), None)
    assert respuesta["statusCode"] == 200
    assert respuesta["body"] == "98765"
    assert respuesta["headers"]["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    ("mode", "token", "challenge"),
    [
        ("subscribe", "token-malo", "98765"),
        ("subscribe", _TOKEN, None),
    ],
)
def test_handler_get_invalido_es_403_json(
    monkeypatch: pytest.MonkeyPatch, *, mode: str | None, token: str | None, challenge: str | None
) -> None:
    """El 403 del caso de uso llega como JSON con el código, sin trazas."""
    _entorno_webhook(monkeypatch)
    respuesta = lambda_webhook.main(_evento_get(mode=mode, token=token, challenge=challenge), None)
    assert respuesta["statusCode"] == 403
    assert json.loads(respuesta["body"]) == {"error": "forbidden"}
    assert respuesta["headers"]["content-type"].startswith("application/json")


def test_handler_post_con_firma_valida_es_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """El POST aceptado responde 200 EVENT_RECEIVED (encolado: Fase 4)."""
    _entorno_webhook(monkeypatch)
    respuesta = lambda_webhook.main(_evento_post(), None)
    assert (respuesta["statusCode"], respuesta["body"]) == (200, "EVENT_RECEIVED")


def test_handler_post_con_firma_invalida_es_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """Firma ausente o incorrecta → 403 con el código estable, jamás el detalle."""
    _entorno_webhook(monkeypatch)
    for evento in (_evento_post(firma=None), _evento_post(firma="sha256=ff")):
        respuesta = lambda_webhook.main(evento, None)
        assert respuesta["statusCode"] == 403
        assert json.loads(respuesta["body"]) == {"error": "invalid_signature"}


def test_handler_acepta_cuerpo_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    """API Gateway puede marcar `isBase64Encoded`: los bytes firmados deben conservarse."""
    _entorno_webhook(monkeypatch)
    evento = _evento_post()
    evento["rawBody"] = base64.b64encode(_PAYLOAD).decode("ascii")
    evento["isBase64Encoded"] = True
    respuesta = lambda_webhook.main(evento, None)
    assert (respuesta["statusCode"], respuesta["body"]) == (200, "EVENT_RECEIVED")


def test_handler_metodo_no_soportado_es_405(monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo GET y POST: cualquier otro método se rechaza sin tocar la firma."""
    _entorno_webhook(monkeypatch)
    respuesta = lambda_webhook.main(_evento_post(metodo="PUT"), None)
    assert respuesta["statusCode"] == 405


def test_handler_falla_al_arrancar_sin_secretos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin secretos en el entorno la Lambda falla al construir (fail fast, no 403)."""
    monkeypatch.setenv("CHATBOT_BEDROCK_MODEL_ID", "modelo-de-prueba")
    monkeypatch.delenv("CHATBOT_WEBHOOK_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("CHATBOT_META_APP_SECRET", raising=False)
    with pytest.raises(ValidationError):
        lambda_webhook.main(_evento_get(), None)


def test_handler_no_filtra_trazas_en_la_respuesta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ningún cuerpo de error contiene texto de excepción ni detalles internos."""
    _entorno_webhook(monkeypatch)
    respuesta = lambda_webhook.main(_evento_post(firma="sha256=ff"), None)
    cuerpo = respuesta["body"].lower()
    for prohibido in ("traceback", "exception", "app_secret", _SECRETO):
        assert prohibido not in cuerpo
