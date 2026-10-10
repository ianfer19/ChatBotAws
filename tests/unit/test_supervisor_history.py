"""Tests de la política de ventana y resumen del supervisor (ROADMAP Paso 8)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pytest

from shared.contracts import AgentName, InboundMessage
from shared.errors import ToolError, ValidationError
from shared.ports import LLMMessage, LLMResult
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.nodes import window_history
from slices.supervisor.application.prompts import TAREA_RESUMEN
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.errors import MissingTurnInputsError
from slices.supervisor.domain.history import (
    RESUMEN_PREFIJO,
    is_summary,
    split_window,
    summary_message,
    without_summary,
)

TENANT = "Sede_Elite_01"
CLIENTE = "57300111111"
AHORA = datetime(2026, 3, 2, 8, 0)


class _FakeLLM:
    """LLM doble: devuelve las salidas guionizadas en orden y registra cada llamada."""

    def __init__(self, salidas: list[str], *, falla: bool = False) -> None:
        """Prepara la cola de salidas (o el modo de fallo del proveedor).

        Args:
            salidas: Textos que devolverá `invoke`, uno por invocación.
            falla: Si es `True`, toda invocación lanza `ToolError` (Bedrock caído).
        """
        self.salidas = list(salidas)
        self.falla = falla
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self,
        *,
        messages: Sequence[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Devuelve la siguiente salida guionizada y registra la llamada.

        Args:
            messages: Entrada recibida (se guarda tal cual para asertar).
            system: Tarea recibida (se guarda para asertar).
            max_tokens: Tope de salida; el doble lo ignora.
            temperature: Muestreo; el doble lo ignora.

        Returns:
            `LLMResult` con el texto guionizado.

        Raises:
            ToolError: Si el doble está en modo de fallo (proveedor no disponible).
        """
        self.calls.append({"messages": list(messages), "system": system})
        if self.falla:
            raise ToolError("bedrock no responde")
        texto = self.salidas.pop(0) if self.salidas else ""
        return LLMResult(text=texto)


class _LectorContexto:
    """Doble del lector de contexto: el nodo de ventana no lo usa (no debe llamarlo)."""

    def get_customer_context(self, *, tenant_id: str, customer_id: str) -> None:
        """Falla el test si alguien lo invoca.

        Args:
            tenant_id: Comercio inyectado.
            customer_id: Cliente inyectado.

        Returns:
            Nunca devuelve: lanza `AssertionError` (el nodo no lee contexto).
        """
        raise AssertionError("window_history no debe leer contexto de cliente")


class _GrafoEspecialista:
    """Doble mínimo del grafo de especialista (Deps lo exige aunque aquí no se use)."""

    def invoke(self, input: object) -> dict[str, object]:
        """Nunca debe invocarse desde el nodo de ventana.

        Args:
            input: Estado que recibiría el especialista.

        Returns:
            Nunca devuelve: lanza `AssertionError`.
        """
        raise AssertionError("window_history no debe invocar especialistas")


def _mensaje(texto: str = "hola") -> InboundMessage:
    """Mensaje normalizado como lo entregaría el gateway (ids ya resueltos).

    Args:
        texto: Texto del cliente.

    Returns:
        `InboundMessage` del tenant de prueba.
    """
    return InboundMessage(
        tenant_id=TENANT,
        correlation_id="corr-1",
        channel="whatsapp",
        emitter_id="1000",
        customer_id=CLIENTE,
        message_id="m-1",
        timestamp=AHORA,
        text=texto,
    )


def _turnos(cantidad: int) -> list[LLMMessage]:
    """Historial sintético en orden cronológico (`turno 0` es el más antiguo).

    Args:
        cantidad: Número de mensajes a crear (alternando roles).

    Returns:
        Lista con `cantidad` mensajes.
    """
    return [
        LLMMessage(role="user" if indice % 2 == 0 else "assistant", content=f"turno {indice}")
        for indice in range(cantidad)
    ]


def _estado(
    historial: list[LLMMessage] | None = None, *, resumen: str | None = None
) -> SupervisorState:
    """Estado de turno para el nodo de ventana.

    Args:
        historial: Ventana a pasar; `None` deja el turno sin historial (caso negativo).
        resumen: Resumen rodante previo, si lo había.

    Returns:
        Estado listo para `window_history`.
    """
    estado = SupervisorState(message=_mensaje())
    if historial is not None:
        estado["history"] = historial
    if resumen is not None:
        estado["summary"] = resumen
    return estado


def _deps(llm: _FakeLLM, *, size: int = 10) -> Deps:
    """Dependencias mínimas para el nodo de ventana (lector y grafo nunca se usan).

    Args:
        llm: Doble guionizado del modelo.
        size: Tamaño de la ventana a probar.

    Returns:
        Dependencias listas para invocar `window_history`.
    """
    return Deps(
        llm=llm,
        context_reader=_LectorContexto(),
        allowed_bots=frozenset[AgentName](),
        appointments_graph=_GrafoEspecialista(),
        history_window_size=size,
    )


# ------------------------------------------------------------------- domain/history


def test_split_window_conserva_los_ultimos_mensajes_y_devuelve_los_desbordados() -> None:
    """La ventana se queda con lo más reciente y los desbordados conservan el orden."""
    historial = _turnos(7)
    conservados, desbordados = split_window(historial, size=4)
    assert conservados == historial[3:]
    assert desbordados == historial[:3]
    assert [m.content for m in desbordados] == ["turno 0", "turno 1", "turno 2"]


def test_split_window_sin_desborde_devuelve_vacio() -> None:
    """Si el historial cabe entero en la ventana, no hay nada que resumir."""
    historial = _turnos(4)
    conservados, desbordados = split_window(historial, size=4)
    assert conservados == historial
    assert desbordados == []


def test_split_window_rechaza_un_tamano_menor_que_uno() -> None:
    """Una ventana de 0 mensajes no tiene significado: falla en el origen."""
    with pytest.raises(ValidationError):
        split_window(_turnos(3), size=0)


def test_resumen_sintetico_es_detectable_y_usa_rol_asistente() -> None:
    """El resumen se reconoce por su prefijo y no puede pasar por texto de cliente."""
    mensaje = summary_message("Ana pidió una mesa")
    assert mensaje.role == "assistant"
    assert mensaje.content == f"{RESUMEN_PREFIJO}Ana pidió una mesa"
    assert is_summary(mensaje)
    assert not is_summary(LLMMessage(role="user", content="quiero una mesa"))


def test_without_summary_quita_solo_los_resumenes() -> None:
    """Re-resumir parte del historial limpio: el resumen previo no viaja al modelo."""
    resumen = summary_message("turnos viejos")
    historial = [resumen, *_turnos(3)]
    assert without_summary(historial) == _turnos(3)


# ----------------------------------------------------------------- nodo window_history


def test_ventana_corta_no_llama_al_llm_y_conserva_todo() -> None:
    """Sin desbordado no hay coste de resumen: el historial pasa intacto."""
    llm = _FakeLLM([])
    historial = _turnos(4)
    resultado = window_history(_estado(historial), deps=_deps(llm, size=10))
    assert resultado["history"] == historial
    assert resultado["summary"] is None
    assert llm.calls == []


def test_desborde_pide_un_resumen_y_recorta_la_ventana() -> None:
    """Con desbordado: una llamada al LLM, resumen al frente y ventana de tamaño fijo."""
    llm = _FakeLLM(["Ana pidió mesa y luego preguntó por el menú"])
    historial = _turnos(7)
    resultado = window_history(_estado(historial), deps=_deps(llm, size=4))

    assert len(llm.calls) == 1
    assert llm.calls[0]["system"] == TAREA_RESUMEN
    entrada = llm.calls[0]["messages"][0].content
    assert "turno 0" in entrada and "turno 2" in entrada
    assert "turno 3" not in entrada

    ventana = resultado["history"]
    assert len(ventana) == 5
    assert ventana[0] == summary_message("Ana pidió mesa y luego preguntó por el menú")
    assert ventana[1:] == historial[3:]
    assert resultado["summary"] == "Ana pidió mesa y luego preguntó por el menú"


def test_resumen_previo_viaja_al_llm_y_se_actualiza() -> None:
    """El resumen rodante acumula: lo previo se pasa al modelo y se reemplaza."""
    llm = _FakeLLM(["Resumen nuevo"])
    resultado = window_history(
        _estado(_turnos(7), resumen="Resumen viejo"),
        deps=_deps(llm, size=4),
    )
    entrada = llm.calls[0]["messages"][0].content
    assert "Resumen previo de la conversacion: Resumen viejo" in entrada
    assert resultado["summary"] == "Resumen nuevo"
    assert resultado["history"][0] == summary_message("Resumen nuevo")


def test_resumen_previo_no_se_resume_a_si_mismo() -> None:
    """La ventana guardada trae el resumen sintético: se quita antes de re-resumir."""
    llm = _FakeLLM(["Resumen nuevo"])
    historial = [summary_message("Resumen viejo"), *_turnos(7)]
    resultado = window_history(_estado(historial), deps=_deps(llm, size=4))

    entrada = llm.calls[0]["messages"][0].content
    assert RESUMEN_PREFIJO not in entrada
    assert sum(1 for m in resultado["history"] if is_summary(m)) == 1


def test_fallo_del_llm_conserva_el_resumen_previo_y_sigue_el_turno() -> None:
    """Bedrock caído no corta la conversación: se mantiene el resumen anterior."""
    llm = _FakeLLM([], falla=True)
    resultado = window_history(
        _estado(_turnos(7), resumen="Resumen viejo"),
        deps=_deps(llm, size=4),
    )
    assert resultado["summary"] == "Resumen viejo"
    assert resultado["history"][0] == summary_message("Resumen viejo")
    assert len(resultado["history"]) == 5


def test_fallo_del_llm_sin_previo_deja_la_ventana_sin_resumen() -> None:
    """Sin resumen previo y con el proveedor caído, el turno sigue solo con la ventana."""
    llm = _FakeLLM([], falla=True)
    resultado = window_history(_estado(_turnos(7)), deps=_deps(llm, size=4))
    assert resultado["summary"] is None
    assert resultado["history"] == _turnos(7)[3:]


def test_salida_vacia_del_llm_conserva_el_resumen_previo() -> None:
    """Una respuesta vacía no pisa el resumen que ya había (nunca se inventa contenido)."""
    llm = _FakeLLM([""])
    resultado = window_history(
        _estado(_turnos(7), resumen="Resumen viejo"),
        deps=_deps(llm, size=4),
    )
    assert resultado["summary"] == "Resumen viejo"
    assert resultado["history"][0] == summary_message("Resumen viejo")


def test_tamano_de_ventana_personalizado() -> None:
    """La ventana respeta el tamaño que la composición inyectó en `Deps`."""
    llm = _FakeLLM(["Resumen corto"])
    historial = _turnos(5)
    resultado = window_history(_estado(historial), deps=_deps(llm, size=2))
    assert len(resultado["history"]) == 3
    assert resultado["history"][1:] == historial[3:]


def test_sin_historial_el_turno_falla() -> None:
    """El nodo exige la ventana igual que `load_context` (requisito 7.2)."""
    with pytest.raises(MissingTurnInputsError):
        window_history(_estado(None), deps=_deps(_FakeLLM([])))
