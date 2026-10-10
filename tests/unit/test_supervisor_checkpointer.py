"""Checkpointer del supervisor: hilos, ventana y resumen entre turnos (Paso 8).

Prueban `build_supervisor_graph(checkpointer=...)` con `PortCheckpointSaver` sobre
un doble en memoria: la conversación sobrevive a invocaciones distintas con el mismo
`thread_id`, no hay fuga de estado entre conversaciones ni entre comercios, el
resumen persiste y los resultados del turno anterior no se heredan al siguiente.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from langgraph.checkpoint.base import RunnableConfig

from adapters.checkpointer import PortCheckpointSaver, thread_id_de
from adapters.in_memory import InMemoryMemoryStore
from shared.contracts import AgentName, CustomerContext, InboundMessage
from shared.ports import LLMMessage, LLMResult
from slices.supervisor.application.graph import build_supervisor_graph
from slices.supervisor.application.prompts import TAREA_RESUMEN
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.history import summary_message
from slices.supervisor.domain.routing import saludo

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Sede_Otro_02"
CLIENTE = "57300111111"
BOTS: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
AHORA = datetime(2026, 3, 2, 8, 0)

JSON_SALUDO = '{"intent": "greeting", "confidence": 0.97}'
JSON_CITA = '{"intent": "appointments", "confidence": 0.95}'
JSON_VENTAS = '{"intent": "sales", "confidence": 0.91}'
JSON_BAJA = '{"intent": "faq", "confidence": 0.2}'


class _FakeLLM:
    """LLM doble: devuelve las salidas guionizadas en orden y registra cada llamada."""

    def __init__(self, salidas: list[str]) -> None:
        """Prepara la cola de salidas.

        Args:
            salidas: Textos que devolverá `invoke`, uno por invocación.
        """
        self.salidas = list(salidas)
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
            messages: Entrada recibida (se guarda para asertar).
            system: Tarea recibida (se guarda para asertar).
            max_tokens: Tope de salida; el doble lo ignora.
            temperature: Muestreo; el doble lo ignora.

        Returns:
            `LLMResult` con el texto guionizado.
        """
        self.calls.append({"messages": list(messages), "system": system})
        texto = self.salidas.pop(0) if self.salidas else "{}"
        return LLMResult(text=texto)


class _LectorContexto:
    """Doble del lector de contexto: siempre devuelve el mismo contexto."""

    def get_customer_context(self, *, tenant_id: str, customer_id: str) -> CustomerContext:
        """Devuelve el contexto fijo del tenant de prueba.

        Args:
            tenant_id: Comercio inyectado por el nodo desde el mensaje.
            customer_id: Cliente inyectado por el nodo desde el mensaje.

        Returns:
            Contexto congelado de ejemplo.
        """
        return CustomerContext(
            tenant_id=tenant_id,
            customer_id=customer_id,
            name="Ana",
            preferences={},
            tags=[],
        )


class _EspecialistaEspia:
    """Doble del grafo de citas: registra invocaciones y devuelve su respuesta."""

    def __init__(self, reply: str = "Respuesta del especialista") -> None:
        """Prepara el especialista.

        Args:
            reply: Texto de `reply` del estado final.
        """
        self._reply = reply
        self.calls: list[Any] = []

    def invoke(self, input: Any) -> dict[str, Any]:
        """Registra la entrada y devuelve el estado simulado.

        Args:
            input: Estado que el supervisor arma para el especialista.

        Returns:
            `{"reply": ...}`.
        """
        self.calls.append(input)
        return {"reply": self._reply}


def _mensaje(texto: str, *, tenant_id: str = TENANT) -> InboundMessage:
    """Mensaje normalizado como lo entregaría el gateway (ids ya resueltos).

    Args:
        texto: Texto del cliente.
        tenant_id: Comercio resuelto en el gateway.

    Returns:
        `InboundMessage` del tenant indicado.
    """
    return InboundMessage(
        tenant_id=tenant_id,
        correlation_id="corr-1",
        channel="whatsapp",
        emitter_id="1000",
        customer_id=CLIENTE,
        message_id="m-1",
        timestamp=AHORA,
        text=texto,
    )


def _turno(texto: str, historial: list[LLMMessage]) -> SupervisorState:
    """Estado de un turno entrante con su ventana (como el llamador sin checkpointer).

    Args:
        texto: Texto del cliente.
        historial: Ventana de historial del turno.

    Returns:
        Estado listo para `invoke`.
    """
    return SupervisorState(message=_mensaje(texto), history=list(historial))


def _historial(cantidad: int = 2) -> list[LLMMessage]:
    """Ventana sintética en orden cronológico.

    Args:
        cantidad: Número de mensajes.

    Returns:
        Lista de mensajes alternando roles.
    """
    return [
        LLMMessage(role="user" if indice % 2 == 0 else "assistant", content=f"turno {indice}")
        for indice in range(cantidad)
    ]


def _config(
    *, tenant_id: str = TENANT, conversation_id: str = "whatsapp:57300111111"
) -> RunnableConfig:
    """Configuración de hilo con el `thread_id` canónico (`tenant#conversacion`).

    Args:
        tenant_id: Comercio dueño del hilo.
        conversation_id: Conversación del canal.

    Returns:
        `RunnableConfig` con el `thread_id` del hilo.
    """
    return {
        "configurable": {
            "thread_id": thread_id_de(tenant_id=tenant_id, conversation_id=conversation_id)
        }
    }


def _grafo(salidas: list[str]) -> tuple[Any, _FakeLLM, _EspecialistaEspia]:
    """Grafo compilado con checkpointer en memoria y todos los dobles a la vista.

    Args:
        salidas: Textos que devolverá el LLM, uno por invocación.

    Returns:
        Tupla (grafo, llm, especialista de citas).
    """
    llm = _FakeLLM(salidas)
    spy = _EspecialistaEspia()
    grafo = build_supervisor_graph(
        llm=llm,
        context_reader=_LectorContexto(),
        allowed_bots=BOTS,
        appointments_graph=spy,
        orders_graph=None,
        faq_graph=None,
        checkpointer=PortCheckpointSaver(store=InMemoryMemoryStore()),
    )
    return grafo, llm, spy


def test_la_conversacion_sobrevive_a_invocaciones_distintas() -> None:
    """Mismo `thread_id`: el segundo turno ve el historial que guardó el primero."""
    grafo, llm, _ = _grafo([JSON_CITA, JSON_SALUDO])
    historial = [
        LLMMessage(role="assistant", content="Hola, ¿en qué te ayudo?"),
        LLMMessage(role="user", content="Quiero preguntar algo"),
    ]
    grafo.invoke(_turno("buenas", historial), config=_config())
    resultado = grafo.invoke(SupervisorState(message=_mensaje("gracias")), config=_config())
    assert llm.calls[1]["messages"] == [
        *historial,
        LLMMessage(role="user", content="gracias"),
    ]
    assert resultado["reply"] == saludo(TENANT)


def test_cero_fuga_entre_conversaciones_del_mismo_comercio() -> None:
    """Hilos distintos del mismo comercio no comparten historial ni resumen."""
    grafo, llm, _ = _grafo([JSON_SALUDO, JSON_SALUDO])
    privado_a = [LLMMessage(role="user", content="turno privado de la conversacion A")]
    grafo.invoke(
        _turno("hola", privado_a),
        config=_config(conversation_id="whatsapp:111111111"),
    )
    privado_b = [LLMMessage(role="user", content="turno privado de la conversacion B")]
    grafo.invoke(
        SupervisorState(message=_mensaje("hola de nuevo"), history=list(privado_b)),
        config=_config(conversation_id="whatsapp:222222222"),
    )
    mensajes_b = llm.calls[1]["messages"]
    assert mensajes_b == [*privado_b, LLMMessage(role="user", content="hola de nuevo")]
    assert all("conversacion A" not in mensaje.content for mensaje in mensajes_b)


def test_cero_fuga_entre_comercios_con_la_misma_conversacion() -> None:
    """El tenant vive en el `thread_id`: mismo id de conversación, comercios distintos."""
    grafo, llm, _ = _grafo([JSON_SALUDO, JSON_SALUDO])
    historial_a = [LLMMessage(role="user", content="pedido del comercio A")]
    grafo.invoke(
        _turno("hola", historial_a),
        config=_config(tenant_id=TENANT, conversation_id="whatsapp:999999999"),
    )
    historial_b = [LLMMessage(role="user", content="pedido del comercio B")]
    grafo.invoke(
        SupervisorState(message=_mensaje("hola", tenant_id=OTRO_TENANT), history=list(historial_b)),
        config=_config(tenant_id=OTRO_TENANT, conversation_id="whatsapp:999999999"),
    )
    mensajes_b = llm.calls[1]["messages"]
    assert mensajes_b == [*historial_b, LLMMessage(role="user", content="hola")]
    assert all("comercio A" not in mensaje.content for mensaje in mensajes_b)


def test_el_resumen_del_hilo_se_persiste_entre_turnos() -> None:
    """El resumen escrito en el turno 1 llega al clasificador del turno 2 sin rehacerlo."""
    grafo, llm, _ = _grafo(["Resumen de los doce turnos.", JSON_SALUDO, JSON_SALUDO])
    historial = [
        LLMMessage(role="user" if indice % 2 == 0 else "assistant", content=f"turno {indice}")
        for indice in range(12)
    ]
    grafo.invoke(_turno("hola", historial), config=_config())
    assert llm.calls[0]["system"] == TAREA_RESUMEN

    resultado = grafo.invoke(SupervisorState(message=_mensaje("sigue")), config=_config())
    assert len(llm.calls) == 3
    assert llm.calls[2]["messages"][0] == summary_message("Resumen de los doce turnos.")
    assert resultado["summary"] == "Resumen de los doce turnos."


def test_las_respuestas_del_turno_anterior_no_se_herelan() -> None:
    """Con checkpointer, `reply` y `route_error` del turno previo no pisan este turno."""
    grafo, llm, _ = _grafo([JSON_BAJA, JSON_VENTAS])
    grafo.invoke(_turno("eh", _historial()), config=_config())
    assert llm.calls[0]["messages"]  # el turno 1 clasificó y respondió (ambiguo)

    resultado = grafo.invoke(
        SupervisorState(message=_mensaje("quiero comprar dos sillas")), config=_config()
    )
    assert resultado["reply"] is None
    assert resultado["route_error"] is None
    assert resultado["routed"].target == "sales"


def test_sin_checkpointer_el_grafo_sigue_igual() -> None:
    """La composición sin checkpointer es retrocompatible: cada turno es aislado."""
    llm = _FakeLLM([JSON_SALUDO, JSON_SALUDO])
    grafo = build_supervisor_graph(
        llm=llm,
        context_reader=_LectorContexto(),
        allowed_bots=BOTS,
        appointments_graph=_EspecialistaEspia(),
        orders_graph=None,
        faq_graph=None,
    )
    primero = grafo.invoke(_turno("hola", _historial()))
    segundo = grafo.invoke(_turno("hola otra vez", _historial()))
    assert primero["reply"] == saludo(TENANT)
    assert segundo["reply"] == saludo(TENANT)
    assert len(llm.calls) == 2
