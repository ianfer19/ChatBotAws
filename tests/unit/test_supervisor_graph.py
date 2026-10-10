"""Tests de los nodos y del grafo end-to-end del supervisor (ROADMAP Paso 4)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pytest

from shared.contracts import AgentName, CustomerContext, InboundMessage
from shared.errors import ToolError
from shared.ports import LLMMessage, LLMResult
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.graph import build_supervisor_graph
from slices.supervisor.application.nodes import classify, load_context, ruta_tras_decidir
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.errors import MissingTurnInputsError
from slices.supervisor.domain.routing import saludo

TENANT = "Sede_Elite_01"
CLIENTE = "57300111111"
BOTS: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
AHORA = datetime(2026, 3, 2, 8, 0)

JSON_SALUDO = '{"intent": "greeting", "confidence": 0.97}'
JSON_CITA = '{"intent": "appointments", "confidence": 0.95}'
JSON_VENTAS = '{"intent": "sales", "confidence": 0.91}'
JSON_PEDIDOS = '{"intent": "orders", "confidence": 0.94}'
JSON_FAQ = '{"intent": "faq", "confidence": 0.92}'
JSON_BAJA = '{"intent": "faq", "confidence": 0.2}'

_MSG_SIN_RESPUESTA = "No pude preparar la respuesta. ¿Puedes repetir tu mensaje?"
_MSG_NO_DISPONIBLE_PARTE = "no está disponible"
_MSG_NO_ENTENDI_PARTE = "No estoy seguro"


class _RelojFijo:
    """Reloj inyectable con hora fija para el almacén de contexto de prueba."""

    def __init__(self, ahora: datetime) -> None:
        """Guarda el instante que devolverá `now`.

        Args:
            ahora: Instante fijo del test.
        """
        self._ahora = ahora

    def now(self) -> datetime:
        """Devuelve el instante fijo del test.

        Returns:
            La hora configurada al construir el reloj.
        """
        return self._ahora


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
            messages: Turno recibido (se guarda tal cual para asertar).
            system: Bloque de sistema recibido (se guarda para asertar el contexto).
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
        texto = self.salidas.pop(0) if self.salidas else "{}"
        return LLMResult(text=texto)


class _LectorContexto:
    """Doble del `ContextReaderPort`: contexto fijo y registro de las lecturas."""

    def __init__(self, contexto: CustomerContext | None) -> None:
        """Prepara el lector con el contexto que devolverá.

        Args:
            contexto: Contexto a devolver, o `None` para simular «turno sin contexto».
        """
        self._contexto = contexto
        self.calls: list[tuple[str, str]] = []

    def get_customer_context(self, *, tenant_id: str, customer_id: str) -> CustomerContext | None:
        """Registra la lectura y devuelve el contexto fijo del doble.

        Args:
            tenant_id: Comercio inyectado por el nodo desde el mensaje.
            customer_id: Cliente inyectado por el nodo desde el mensaje.

        Returns:
            El contexto configurado (posiblemente `None`).
        """
        self.calls.append((tenant_id, customer_id))
        return self._contexto


class _EspecialistaEspia:
    """Doble del grafo de citas: registra las invocaciones y devuelve su respuesta."""

    def __init__(self, reply: str | None = "Respuesta del especialista de citas") -> None:
        """Prepara el especialista con la respuesta que devolverá.

        Args:
            reply: Texto de `reply` del estado final, o `None` para devolver `{}`.
        """
        self._reply = reply
        self.calls: list[Any] = []

    def invoke(self, input: Any) -> dict[str, Any]:
        """Registra la entrada recibida y devuelve el estado final simulado.

        Args:
            input: Estado que el supervisor arma para el especialista.

        Returns:
            `{"reply": ...}` o `{}` según lo configurado.
        """
        self.calls.append(input)
        if self._reply is None:
            return {}
        return {"reply": self._reply}


def _mensaje(texto: str, *, correlation_id: str = "corr-1") -> InboundMessage:
    """Mensaje normalizado como lo entregaría el gateway (ids ya resueltos).

    Args:
        texto: Texto del cliente.
        correlation_id: Identificador del turno.

    Returns:
        `InboundMessage` del tenant de prueba.
    """
    return InboundMessage(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        channel="whatsapp",
        customer_id=CLIENTE,
        message_id="m-1",
        timestamp=AHORA,
        text=texto,
    )


def _historial() -> list[LLMMessage]:
    """Ventana de un turno previo: asistente y cliente (siempre presente en un turno).

    Returns:
        Lista con dos mensajes de ejemplo.
    """
    return [
        LLMMessage(role="assistant", content="Hola, ¿en qué te ayudo?"),
        LLMMessage(role="user", content="Quería preguntar algo"),
    ]


def _turno(texto: str, *, con_historial: bool = True) -> SupervisorState:
    """Estado de un turno: el mensaje del gateway (+ historial salvo en el caso negativo).

    Args:
        texto: Texto del cliente.
        con_historial: Si es `False`, omite la ventana para probar el guard 7.2.

    Returns:
        Estado listo para `invoke` del grafo.
    """
    estado = SupervisorState(message=_mensaje(texto))
    if con_historial:
        estado["history"] = _historial()
    return estado


def _contexto() -> CustomerContext:
    """Contexto de cliente del tenant de prueba con nombre y preferencias.

    Returns:
        Contexto congelado de ejemplo.
    """
    return CustomerContext(
        tenant_id=TENANT,
        customer_id=CLIENTE,
        name="Ana",
        preferences={"idioma": "es"},
        tags=["vip"],
    )


def _deps(
    llm: _FakeLLM,
    *,
    lector: _LectorContexto,
    bots: frozenset[AgentName] = BOTS,
    especialista: _EspecialistaEspia | None = None,
    orders_especialista: _EspecialistaEspia | None = None,
    con_orders: bool = True,
    faq_especialista: _EspecialistaEspia | None = None,
    con_faq: bool = True,
) -> Deps:
    """Construye las dependencias de los nodos con dobles.

    Args:
        llm: Doble guionizado del modelo.
        lector: Doble del lector de contexto.
        bots: Entitlements del comercio de prueba.
        especialista: Doble del grafo de citas (se crea uno si no viene).
        orders_especialista: Doble del grafo de pedidos (se crea uno si no viene).
        con_orders: Si es `False`, no se inyecta grafo de pedidos (`orders_graph=None`).
        faq_especialista: Doble del grafo faq (se crea uno si no viene).
        con_faq: Si es `False`, no se inyecta grafo faq (`faq_graph=None`).

    Returns:
        Dependencias listas para los nodos sueltos.
    """
    return Deps(
        llm=llm,
        context_reader=lector,
        allowed_bots=bots,
        appointments_graph=especialista or _EspecialistaEspia(),
        orders_graph=(orders_especialista or _EspecialistaEspia("Respuesta de pedidos"))
        if con_orders
        else None,
        faq_graph=(faq_especialista or _EspecialistaEspia("Respuesta del faq"))
        if con_faq
        else None,
    )


def _grafo(
    salidas: list[str],
    *,
    con_contexto: bool = True,
    bots: frozenset[AgentName] = BOTS,
    especialista: _EspecialistaEspia | None = None,
    orders_especialista: _EspecialistaEspia | None = None,
    con_orders: bool = True,
    faq_especialista: _EspecialistaEspia | None = None,
    con_faq: bool = True,
    falla: bool = False,
) -> tuple[Any, _FakeLLM, _LectorContexto, _EspecialistaEspia, _EspecialistaEspia | None]:
    """Grafo compilado con todos los dobles a la vista.

    Args:
        salidas: Textos que devolverá el LLM, uno por invocación.
        con_contexto: Si es `False`, el lector devuelve `None` («turno sin contexto»).
        bots: Entitlements del comercio.
        especialista: Doble del grafo de citas reutilizable entre tests.
        orders_especialista: Doble del grafo de pedidos reutilizable entre tests.
        con_orders: Si es `False`, el grafo se compone sin grafo de pedidos.
        faq_especialista: Doble del grafo faq reutilizable entre tests (el que
            pasa la prueba que lo crea).
        con_faq: Si es `False`, el grafo se compone sin grafo faq.
        falla: Si es `True`, el LLM falla siempre (Bedrock caído).

    Returns:
        Tupla (grafo, llm, lector, especialista, orders_especialista o `None`).
    """
    llm = _FakeLLM(salidas, falla=falla)
    lector = _LectorContexto(_contexto() if con_contexto else None)
    spy = especialista or _EspecialistaEspia()
    spy_orders = orders_especialista or _EspecialistaEspia("Respuesta de pedidos")
    spy_faq = faq_especialista or _EspecialistaEspia("Respuesta del faq")
    grafo = build_supervisor_graph(
        llm=llm,
        context_reader=lector,
        allowed_bots=bots,
        appointments_graph=spy,
        orders_graph=spy_orders if con_orders else None,
        faq_graph=spy_faq if con_faq else None,
    )
    return grafo, llm, lector, spy, spy_orders if con_orders else None


# --------------------------------------------------------------------- load_context


def test_load_context_inyecta_el_contexto_y_lee_los_ids_del_mensaje() -> None:
    """El contexto se pide SIEMPRE con los ids del mensaje (nunca del payload del LLM)."""
    lector = _LectorContexto(_contexto())
    estado = load_context(_turno("hola"), deps=_deps(_FakeLLM([]), lector=lector))
    assert estado["context"].name == "Ana"
    assert lector.calls == [(TENANT, CLIENTE)]


def test_turno_sin_historial_falla() -> None:
    """Regresión 7.2: un turno sin ventana de historial no avanza ni clasifica."""
    grafo, _, _, _, _ = _grafo([JSON_SALUDO])
    with pytest.raises(MissingTurnInputsError):
        grafo.invoke(_turno("hola", con_historial=False))


def test_turno_sin_contexto_falla() -> None:
    """Regresión 7.2: un turno cuyo lector devuelve `None` falla en el primer nodo."""
    grafo, _, _, _, _ = _grafo([JSON_SALUDO], con_contexto=False)
    with pytest.raises(MissingTurnInputsError):
        grafo.invoke(_turno("hola"))


def test_classify_directo_sin_contexto_ni_historial_falla() -> None:
    """Defensa en profundidad: el propio clasificador rechaza un prompt incompleto."""
    deps = _deps(_FakeLLM([JSON_SALUDO]), lector=_LectorContexto(_contexto()))
    mensaje_solo = SupervisorState(message=_mensaje("hola"))
    with pytest.raises(MissingTurnInputsError):
        classify(mensaje_solo, deps=deps)
    con_contexto = SupervisorState(message=_mensaje("hola"), context=_contexto())
    with pytest.raises(MissingTurnInputsError):
        classify(con_contexto, deps=deps)


# ------------------------------------------------------------------------- classify


def test_prompt_del_clasificador_lleva_contexto_e_historial() -> None:
    """Todo turno llega al modelo con el bloque de contexto y la ventana completa."""
    grafo, llm, _, _, _ = _grafo([JSON_SALUDO])
    grafo.invoke(_turno("Hola, buenos días"))
    system = llm.calls[0]["system"]
    mensajes = llm.calls[0]["messages"]
    assert "Contexto del turno" in system
    assert f"cliente: {CLIENTE}" in system
    assert mensajes == [*_historial(), LLMMessage(role="user", content="Hola, buenos días")]


def test_json_ilegible_dos_veces_cae_en_ruta_segura() -> None:
    """Dos salidas que no son JSON → decisión ambigua y respuesta honesta, sin acciones."""
    grafo, llm, _, spy, _ = _grafo(["hola", "sigue sin ser json"])
    estado = grafo.invoke(_turno("algo raro"))
    assert len(llm.calls) == 2
    assert estado["route_error"] == "ambiguous_intent"
    assert _MSG_NO_ENTENDI_PARTE in estado["reply"]
    assert spy.calls == []


def test_fallo_de_bedrock_usa_palabras_clave(caplog: pytest.LogCaptureFixture) -> None:
    """Proveedor caído → clasificación por palabras clave con log, sin tumbar el turno."""
    grafo, _, _, spy, _ = _grafo(["nunca se usa"], falla=True)
    with caplog.at_level("WARNING"):
        estado = grafo.invoke(_turno("Quiero una cita el viernes"))
    assert estado["target"] == "appointments"
    assert len(spy.calls) == 1
    assert any("supervisor.keyword_fallback" in record.getMessage() for record in caplog.records)


# --------------------------------------------------------------------------- saludo


def test_saludo_responde_al_supervisor_sin_invocar_a_nadie() -> None:
    """Regresión 7.2: el saludo nunca enruta a ventas ni invoca especialistas/tools."""
    grafo, _, lector, spy, _ = _grafo([JSON_SALUDO], bots=frozenset())
    estado = grafo.invoke(_turno("Hola, buenos días"))
    assert estado["reply"] == saludo(TENANT)
    assert estado["target"] == "supervisor"
    assert "routed" not in estado
    assert spy.calls == []
    assert lector.calls == [(TENANT, CLIENTE)]


def test_smalltalk_tambien_tiene_ruta_propia() -> None:
    """`smalltalk` comparte la ruta del saludo: respuesta neutral del supervisor."""
    grafo, _, _, spy, _ = _grafo(['{"intent": "smalltalk", "confidence": 0.9}'], bots=frozenset())
    estado = grafo.invoke(_turno("gracias, que estés bien"))
    assert estado["target"] == "supervisor"
    assert estado["reply"] == saludo(TENANT)
    assert spy.calls == []


# ------------------------------------------------------------------- especialistas


def test_turno_de_citas_invoca_el_grafo_y_conserva_ids() -> None:
    """La ruta de citas ejecuta el especialista y devuelve su respuesta y `RoutedTurn`."""
    especialista = _EspecialistaEspia("Aquí tienes los huecos del lunes")
    grafo, _, _, _, _ = _grafo([JSON_CITA], especialista=especialista)
    estado = grafo.invoke(_turno("Quiero una cita"))
    assert especialista.calls == [
        {
            "tenant_id": TENANT,
            "correlation_id": "corr-1",
            "conversation_id": "whatsapp:57300111111",
            "user_message": "Quiero una cita",
            "history": _historial(),
        }
    ]
    assert estado["reply"] == "Aquí tienes los huecos del lunes"
    assert estado["routed"].target == "appointments"
    assert estado["routed"].intent == "appointments"
    assert estado["routed"].message.tenant_id == TENANT
    assert estado["routed"].message.correlation_id == "corr-1"


def test_especialista_sin_respuesta_degrada_a_mensaje_honesto() -> None:
    """Si el especialista no redacta, el canal nunca recibe un turno vacío."""
    grafo, _, _, _, _ = _grafo([JSON_CITA], especialista=_EspecialistaEspia(None))
    estado = grafo.invoke(_turno("Quiero una cita"))
    assert estado["reply"] == _MSG_SIN_RESPUESTA
    assert estado["routed"].target == "appointments"


def test_ventas_enruta_al_agente_sin_respuesta_del_supervisor() -> None:
    """`sales` deja el `RoutedTurn` listo para el futuro agente, sin reply propio."""
    grafo, _, _, spy, _ = _grafo([JSON_VENTAS])
    estado = grafo.invoke(_turno("Quiero comprar dos sillas"))
    assert estado["target"] == "sales"
    assert estado["routed"].target == "sales"
    assert "reply" not in estado
    assert spy.calls == []


# ------------------------------------------------------------------ errores de ruta


def test_bot_no_habilitado_responde_sin_invocar() -> None:
    """Comercio sin citas: respuesta del supervisor y cero llamadas al especialista."""
    bots: frozenset[AgentName] = frozenset({"sales", "faq"})
    grafo, _, _, spy, _ = _grafo([JSON_CITA], bots=bots)
    estado = grafo.invoke(_turno("Quiero una cita"))
    assert estado["route_error"] == "intent_not_allowed"
    assert _MSG_NO_DISPONIBLE_PARTE in estado["reply"]
    assert "target" not in estado
    assert spy.calls == []


def test_confianza_baja_responde_sin_invocar() -> None:
    """Confianza bajo el umbral → ruta segura con respuesta honesta, sin acciones."""
    grafo, _, _, spy, _ = _grafo([JSON_BAJA])
    estado = grafo.invoke(_turno("eso"))
    assert estado["route_error"] == "ambiguous_intent"
    assert _MSG_NO_ENTENDI_PARTE in estado["reply"]
    assert spy.calls == []


# ------------------------------------------------------------------------ pedidos (Fase 3)


def test_turno_de_pedidos_invoca_el_grafo_de_orders() -> None:
    """La ruta de pedidos ejecuta su especialista con los ids resueltos en el supervisor."""
    spy_orders = _EspecialistaEspia("Tu pedido se armó.")
    grafo, _, _, spy, _ = _grafo([JSON_PEDIDOS], orders_especialista=spy_orders)
    estado = grafo.invoke(_turno("Quiero pedir unas alitas"))
    assert spy.calls == []
    assert spy_orders.calls == [
        {
            "tenant_id": TENANT,
            "correlation_id": "corr-1",
            "conversation_id": "whatsapp:57300111111",
            "user_message": "Quiero pedir unas alitas",
            "history": _historial(),
        }
    ]
    assert estado["reply"] == "Tu pedido se armó."
    assert estado["routed"].target == "orders"
    assert estado["routed"].intent == "orders"
    assert estado["routed"].message.tenant_id == TENANT


def test_pedidos_sin_grafo_cableado_dejan_el_turno_en_pendiente() -> None:
    """Sin `orders_graph` (composición previa) el turno queda enrutado y sin reply."""
    grafo, _, _, spy, _ = _grafo([JSON_PEDIDOS], con_orders=False)
    estado = grafo.invoke(_turno("Quiero pedir unas alitas"))
    assert spy.calls == []
    assert estado["routed"].target == "orders"
    assert estado["routed"].intent == "orders"
    assert "reply" not in estado
    assert "route_error" not in estado


def test_ruta_tras_decidir_solo_manda_a_pedidos_si_hay_grafo() -> None:
    """La ruta condicional distingue `route_orders` de `route_pending` según el DI."""
    lector = _LectorContexto(_contexto())
    con_grafo = _deps(_FakeLLM([]), lector=lector)
    sin_grafo = _deps(_FakeLLM([]), lector=lector, con_orders=False)
    turno = SupervisorState(message=_mensaje("Quiero pedir"), target="orders")
    assert ruta_tras_decidir(turno, deps=con_grafo) == "route_orders"
    assert ruta_tras_decidir(turno, deps=sin_grafo) == "route_pending"


# ------------------------------------------------------------------------- faq (Paso 7)


def test_turno_de_faq_invoca_el_grafo_de_faq() -> None:
    """La ruta FAQ ejecuta su especialista con los ids resueltos en el supervisor."""
    spy_faq = _EspecialistaEspia("Según la FAQ, abrimos de lunes a sabado.")
    grafo, _, _, spy, _ = _grafo([JSON_FAQ], faq_especialista=spy_faq)
    estado = grafo.invoke(_turno("¿Cual es el horario de apertura?"))
    assert spy.calls == []
    assert spy_faq.calls == [
        {
            "tenant_id": TENANT,
            "correlation_id": "corr-1",
            "user_message": "¿Cual es el horario de apertura?",
            "history": _historial(),
        }
    ]
    assert estado["reply"] == "Según la FAQ, abrimos de lunes a sabado."
    assert estado["routed"].target == "faq"
    assert estado["routed"].intent == "faq"
    assert estado["routed"].message.tenant_id == TENANT


def test_faq_sin_grafo_cableado_deja_el_turno_en_pendiente() -> None:
    """Sin `faq_graph` (composición previa) el turno queda enrutado y sin reply."""
    grafo, _, _, spy, _ = _grafo([JSON_FAQ], con_faq=False)
    estado = grafo.invoke(_turno("¿Cual es el horario de apertura?"))
    assert spy.calls == []
    assert estado["routed"].target == "faq"
    assert estado["routed"].intent == "faq"
    assert "reply" not in estado
    assert "route_error" not in estado


def test_ruta_tras_decidir_solo_manda_a_faq_si_hay_grafo() -> None:
    """La ruta condicional distingue `route_faq` de `route_pending` según el DI."""
    lector = _LectorContexto(_contexto())
    con_grafo = _deps(_FakeLLM([]), lector=lector)
    sin_grafo = _deps(_FakeLLM([]), lector=lector, con_faq=False)
    turno = SupervisorState(message=_mensaje("algo"), target="faq")
    assert ruta_tras_decidir(turno, deps=con_grafo) == "route_faq"
    assert ruta_tras_decidir(turno, deps=sin_grafo) == "route_pending"
