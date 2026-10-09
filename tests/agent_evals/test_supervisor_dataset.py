"""Ejecutor del dataset de enrutado del supervisor (regresión de saludo, Paso 4).

Recorre `datasets/supervisor_routing.json` con un LLM doble que devuelve la
clasificación de cada caso y falla el build si el saludo se enruta a ventas o invoca a
un especialista (requisito 7.2 y fila `greeting_01` de `tests/agent_evals/README.md`).
El lector de contexto es el real de `customer_context`; el runner con modelo real llega
en el Paso 14.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from shared.contracts import AgentName, InboundMessage
from shared.ports import LLMMessage, LLMResult
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore
from slices.supervisor.application.graph import build_supervisor_graph

_RUTA_DATASET = Path(__file__).resolve().parent / "datasets" / "supervisor_routing.json"
_DATOS: dict[str, Any] = json.loads(_RUTA_DATASET.read_text(encoding="utf-8"))
CASOS: list[dict[str, Any]] = _DATOS["casos"]

BOTS_COMPLETOS: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
MSG_ESPECIALISTA = "Respuesta del especialista de citas"
AHORA = datetime(2026, 3, 2, 8, 0)

_REPLICAS: dict[str, str] = {
    "saludo": "Buenas, bienvenido a Sede_Elite_01",
    "especialista": MSG_ESPECIALISTA,
    "servicio_no_disponible": "no está disponible",
    "no_entendido": "No estoy seguro",
}
# Fragmentos que distinguen cada kind de `reply` esperado (subcadena sobre la respuesta).


class _RelojFijo:
    """Reloj fijo para el almacén de contexto real del executor."""

    def __init__(self, ahora: datetime) -> None:
        """Guarda el instante fijo.

        Args:
            ahora: Instante del test.
        """
        self._ahora = ahora

    def now(self) -> datetime:
        """Devuelve el instante fijo.

        Returns:
            La hora configurada.
        """
        return self._ahora


class _FakeLLM:
    """LLM doble con la única clasificación que pide el caso del dataset."""

    def __init__(self, salida: str) -> None:
        """Prepara el doble con su salida.

        Args:
            salida: JSON de clasificación del caso.
        """
        self._salida = salida
        self.calls: int = 0

    def invoke(
        self,
        *,
        messages: Sequence[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Devuelve la clasificación del caso y cuenta la invocación.

        Args:
            messages: Turno recibido; el doble lo ignora.
            system: Prompt recibido; el doble lo ignora.
            max_tokens: Tope de salida; el doble lo ignora.
            temperature: Muestreo; el doble lo ignora.

        Returns:
            `LLMResult` con el JSON del caso.
        """
        del messages, system, max_tokens, temperature
        self.calls += 1
        return LLMResult(text=self._salida)


class _EspecialistaEspia:
    """Grafo de citas doble: registra invocaciones y responde con su mensaje fijo."""

    def __init__(self) -> None:
        """Inicializa el registro de invocaciones."""
        self.calls: list[Any] = []

    def invoke(self, input: Any) -> dict[str, Any]:
        """Registra la entrada y devuelve el estado final simulado.

        Args:
            input: Estado que arma el supervisor para el especialista.

        Returns:
            `{"reply": ...}` con la respuesta fija del doble.
        """
        self.calls.append(input)
        return {"reply": MSG_ESPECIALISTA}


def _mensaje(caso: dict[str, Any]) -> InboundMessage:
    """Mensaje normalizado del caso (el tenant siempre viene del dataset).

    Args:
        caso: Caso del dataset.

    Returns:
        `InboundMessage` sintético con los ids resueltos.
    """
    entrada = caso["entrada"]
    return InboundMessage(
        tenant_id=entrada["tenant"],
        correlation_id=f"corr-{caso['id']}",
        channel="whatsapp",
        customer_id="57300999999",
        message_id=f"m-{caso['id']}",
        timestamp=AHORA,
        text=entrada["mensaje"],
    )


def _historial(caso: dict[str, Any]) -> list[LLMMessage]:
    """Ventana de historial declarada en el caso (puede ser vacía, pero presente).

    Args:
        caso: Caso del dataset.

    Returns:
        Mensajes del historial ya tipados.
    """
    return [LLMMessage.model_validate(item) for item in caso["entrada"].get("historial", [])]


def _ejecutar(caso: dict[str, Any]) -> tuple[Any, _EspecialistaEspia]:
    """Corre un caso completo por el grafo real con el lector de contexto real.

    Args:
        caso: Caso del dataset.

    Returns:
        Tupla (estado final, especialista espía).
    """
    reloj = _RelojFijo(AHORA)
    llm = _FakeLLM(json.dumps(caso["llm"], ensure_ascii=False))
    lector = CustomerContextTools(store=InMemoryCustomerContextStore(clock=reloj), clock=reloj)
    especialista = _EspecialistaEspia()
    bots: frozenset[AgentName] = frozenset(
        caso["entrada"].get("allowed_bots", sorted(BOTS_COMPLETOS))
    )
    grafo = build_supervisor_graph(
        llm=llm,
        context_reader=lector,
        allowed_bots=bots,
        appointments_graph=especialista,
    )
    estado = grafo.invoke({"message": _mensaje(caso), "history": _historial(caso)})
    return estado, especialista


def _verificar_reply(esperado: str | None, estado: Any) -> None:
    """Comprueba el kind de `reply` esperado por el caso.

    Args:
        esperado: `"saludo"`, `"especialista"`, `"servicio_no_disponible"`,
            `"no_entendido"` o `None` (sin respuesta directa).
        estado: Estado final devuelto por el grafo.

    Raises:
        AssertionError: Si no hay reply o no contiene el fragmento del kind.
    """
    if esperado is None:
        assert "reply" not in estado, f"no se esperaba reply y vino: {estado.get('reply')!r}"
        return
    assert "reply" in estado, f"se esperaba reply ({esperado}) y no lo hay"
    fragmento = _REPLICAS[esperado]
    assert (
        fragmento in estado["reply"]
    ), f"reply {estado['reply']!r} no contiene el fragmento de {esperado!r}"


@pytest.mark.parametrize("caso", CASOS, ids=[caso["id"] for caso in CASOS])
def test_caso_de_enrutado(caso: dict[str, Any]) -> None:
    """Ejecuta un caso del dataset y verifica destino, errores, reply y especialista."""
    estado, especialista = _ejecutar(caso)
    esperado = caso["esperado"]

    if esperado["target"] is None:
        assert "target" not in estado
    else:
        assert estado["target"] == esperado["target"]

    if esperado["route_error"] is None:
        assert "route_error" not in estado
    else:
        assert estado["route_error"] == esperado["route_error"]

    invocado = len(especialista.calls) > 0
    assert invocado is esperado["invoca_especialista"]

    if esperado["reply"] == "saludo":
        assert estado["reply"].startswith("Buenas, bienvenido a Sede_Elite_01")
        assert "routed" not in estado
    else:
        _verificar_reply(esperado["reply"], estado)

    if esperado["invoca_especialista"]:
        assert estado["routed"].target == "appointments"
        assert estado["routed"].message.correlation_id == f"corr-{caso['id']}"
