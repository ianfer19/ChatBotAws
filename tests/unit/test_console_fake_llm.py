"""Tests del LLM simulado de la consola: JSON válido por tarea y registro del prompt."""

import json

from handlers.console_fake_llm import FakeLLM
from shared.ports import LLMMessage

_MENSAJE = [LLMMessage(role="user", content="hola")]


def test_clasifica_por_palabras() -> None:
    llm = FakeLLM()
    salida = llm.invoke(messages=_MENSAJE, system="TAREA: clasifica el turno")
    datos = json.loads(salida.text)
    assert datos == {"intent": "greeting", "confidence": 0.9}


def test_clasifica_cita_pedido_y_faq() -> None:
    llm = FakeLLM()
    assert (
        json.loads(
            llm.invoke(
                messages=[LLMMessage(role="user", content="quiero una cita")],
                system="TAREA: clasifica",
            ).text
        )["intent"]
        == "appointments"
    )
    assert (
        json.loads(
            llm.invoke(
                messages=[LLMMessage(role="user", content="quiero pedir comida")],
                system="TAREA: clasifica",
            ).text
        )["intent"]
        == "orders"
    )
    assert (
        json.loads(
            llm.invoke(
                messages=[LLMMessage(role="user", content="cual es el horario")],
                system="TAREA: clasifica",
            ).text
        )["intent"]
        == "faq"
    )


def test_citas_y_pedidos_devuelven_json_valido() -> None:
    llm = FakeLLM()
    citas = json.loads(
        llm.invoke(messages=_MENSAJE, system="TAREA: hoy es 2026-01-01 (jueves)").text
    )
    pedidos = json.loads(llm.invoke(messages=_MENSAJE, system="TAREA: ahora es 2026-01-01").text)
    assert citas["action"] == "reply"
    assert "reply" in citas
    assert pedidos["action"] == "reply"
    assert pedidos["items"] == []


def test_pendiente_ecoa_el_hash_y_pasa() -> None:
    llm = FakeLLM()
    salida = llm.invoke(
        messages=_MENSAJE,
        system="TAREA: decide si responde a la propuesta\npayload_hash: abc123",
    )
    assert json.loads(salida.text) == {"decision": "pass", "payload_hash": "abc123"}


def test_registra_el_system_para_verificar_overrides() -> None:
    llm = FakeLLM()
    llm.invoke(messages=_MENSAJE, system="TAREA: clasifica\nPROMPT PROPIO")
    assert "PROMPT PROPIO" in (llm.last_system or "")
