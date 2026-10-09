"""Tests de los nodos y del grafo end-to-end de pedidos (Paso 5: propose/commit)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, get_args

import pytest

from adapters.in_memory import InMemoryDraftStore
from shared.contracts.pending import ConfirmationPolicy, DraftStatus
from shared.errors import ToolError
from shared.ports import LLMMessage, LLMResult
from slices.orders.application.deps import Deps
from slices.orders.application.graph import build_order_graph
from slices.orders.application.nodes import (
    call_tool,
    need_more,
    respond,
    ruta_confirmacion,
    ruta_tras_accion,
    select_action,
    understand,
    validate,
    validate_result,
)
from slices.orders.application.nodes.select_action import ALLOWED_TOOLS
from slices.orders.application.schemas import (
    KitchenHoursDay,
    OrderProposal,
    OrderView,
    ToolName,
    ToolResult,
)
from slices.orders.application.state import AgentState
from slices.orders.application.tools import OrderTools
from slices.orders.domain.entities import Order, OrderItem, Product
from slices.orders.infrastructure.in_memory import (
    InMemoryCatalog,
    InMemoryLegacyOrders,
    InMemoryOrderRepository,
)

TENANT = "Sede_Elite_01"
CONVERSACION = "whatsapp:57300111111"
COCINA_LUNES = KitchenHoursDay(weekday=0, open_time="11:00", close_time="15:00")
# Mensaje con los nombres literales de los ítems: la política puede ir a `AUTO`.
_MSG_EXPLICITA = "quiero Alitas BBQ y una Coca-Cola"

_CATALOGO = (
    Product(tenant_id=TENANT, sku="A-100", name="Alitas BBQ", price=18_000, category="entradas"),
    Product(tenant_id=TENANT, sku="P-100", name="Coca-Cola", price=5_000, category="bebidas"),
)

JSON_PEDIR = (
    '{"action": "propose_order", "query": null, "category": null, "order_id": null, '
    '"items": [{"sku": "A-100", "quantity": 2}, {"sku": "P-100", "quantity": 1}], '
    '"reply": null}'
)
JSON_MENU = (
    '{"action": "get_menu", "query": null, "category": "bebidas", "order_id": null, '
    '"items": [], "reply": null}'
)
JSON_SALUDO = (
    '{"action": "reply", "query": null, "category": null, "order_id": null, '
    '"items": [], "reply": "Hola, soy el asistente de pedidos."}'
)
JSON_CON_TENANT_AJENO = (
    '{"action": "propose_order", "query": null, "category": null, "order_id": null, '
    '"items": [{"sku": "A-100", "quantity": 2}], "reply": null, '
    '"tenant_id": "Comercio_Ajeno_99"}'
)


class _RelojFijo:
    """Reloj inyectable con hora fija para que el horario de cocina sea estable."""

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

    def __init__(self, salidas: list[str]) -> None:
        """Prepara la cola de salidas del doble.

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
            messages: Historial recibido (se guarda tal cual para asertar).
            system: Bloque de sistema recibido (se guarda para asertar el contexto).
            max_tokens: Tope de salida; el doble lo ignora.
            temperature: Muestreo; el doble lo ignora.

        Returns:
            `LLMResult` con el texto guionizado.
        """
        self.calls.append({"messages": list(messages), "system": system})
        texto = self.salidas.pop(0) if self.salidas else "respuesta-de-test"
        return LLMResult(text=texto)


def _turno(
    mensaje: str,
    *,
    correlation_id: str = "corr-1",
    proposal: OrderProposal | None = None,
    missing_fields: list[str] | None = None,
    tool_name: ToolName | None = None,
    tool_result: ToolResult | None = None,
    tool_error: dict[str, str] | None = None,
    needs_confirmation: bool | None = None,
) -> AgentState:
    """Estado de un turno: contexto resuelto como en el gateway más los campos pedidos.

    Args:
        mensaje: Texto del cliente.
        correlation_id: Identificador del turno.
        proposal: Propuesta ya interpretada (salida de `understand`).
        missing_fields: Campos faltantes detectados (salida de `validate`).
        tool_name: Tool elegida (salida de `select_action`).
        tool_result: Salida de la tool (salida de `call_tool`).
        tool_error: Error tipado traducido (salida de `call_tool`).
        needs_confirmation: Si el resultado pide confirmación (`validate_result`).

    Returns:
        Estado listo para alimentar el nodo que se esté probando.
    """
    estado = AgentState(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        conversation_id=CONVERSACION,
        user_message=mensaje,
    )
    if proposal is not None:
        estado["proposal"] = proposal
    if missing_fields is not None:
        estado["missing_fields"] = missing_fields
    if tool_name is not None:
        estado["tool_name"] = tool_name
    if tool_result is not None:
        estado["tool_result"] = tool_result
    if tool_error is not None:
        estado["tool_error"] = tool_error
    if needs_confirmation is not None:
        estado["needs_confirmation"] = needs_confirmation
    return estado


def _deps(
    llm: _FakeLLM,
    *,
    repo: InMemoryOrderRepository | None = None,
) -> tuple[Deps, InMemoryOrderRepository]:
    """Construye las dependencias de los nodos con dobles en memoria.

    Args:
        llm: Doble guionizado del modelo.
        repo: Repositorio reutilizable entre nodos.

    Returns:
        Tupla con las dependencias y su repositorio.
    """
    repositorio = repo if repo is not None else InMemoryOrderRepository()
    reloj = _RelojFijo(datetime(2026, 3, 2, 12, 0))
    deps = Deps(
        llm=llm,
        tools=OrderTools(
            legacy=InMemoryLegacyOrders(repositorio, clock=reloj),
            catalog=InMemoryCatalog(_CATALOGO),
            drafts=InMemoryDraftStore(clock=reloj),
            clock=reloj,
            kitchen_hours=(COCINA_LUNES,),
        ),
        clock=reloj,
    )
    return deps, repositorio


def _propuesta_pedir() -> OrderProposal:
    """Propuesta completa de pedido (sin datos faltantes).

    Returns:
        Propuesta validada con el carrito ya armado.
    """
    return OrderProposal.model_validate(
        {
            "action": "propose_order",
            "items": [{"sku": "A-100", "quantity": 2}, {"sku": "P-100", "quantity": 1}],
        }
    )


def _resultado_esperando() -> ToolResult:
    """Salida de `propose_order` con la política `CONFIRM` (sin ejecutar).

    Returns:
        `ToolResult` con el draft a la espera de confirmación.
    """
    return ToolResult(
        tool="propose_order",
        draft_id="drf-espera",
        draft_status=DraftStatus.AWAITING_CONFIRMATION,
        policy=ConfirmationPolicy.CONFIRM,
        policy_reasons=("item_inferido:A-100",),
    )


def _resultado_commiteado() -> ToolResult:
    """Salida de `propose_order` ya commiteada (política `AUTO`).

    Returns:
        `ToolResult` con el pedido creado y el draft `COMMITTED`.
    """
    return ToolResult(
        tool="propose_order",
        order=OrderView(
            id="ord-1",
            status="ABIERTA",
            total=41_000,
            items=(
                OrderItem(sku="A-100", quantity=2),
                OrderItem(sku="P-100", quantity=1),
            ),
        ),
        draft_id="drf-hecho",
        draft_status=DraftStatus.COMMITTED,
        policy=ConfirmationPolicy.AUTO,
    )


def _grafo(
    salidas: list[str],
    *,
    repo: InMemoryOrderRepository | None = None,
) -> tuple[Any, _FakeLLM, InMemoryOrderRepository]:
    """Grafo compilado con LLM guionizado y dobles en memoria.

    Args:
        salidas: Textos que devolverá el LLM, uno por invocación.
        repo: Repositorio reutilizable para asertar sobre lo persistido.

    Returns:
        Tupla con el grafo, el doble de LLM y el repositorio.
    """
    llm = _FakeLLM(salidas)
    repositorio = repo if repo is not None else InMemoryOrderRepository()
    reloj = _RelojFijo(datetime(2026, 3, 2, 12, 0))
    grafo = build_order_graph(
        llm=llm,
        legacy=InMemoryLegacyOrders(repositorio, clock=reloj),
        catalog=InMemoryCatalog(_CATALOGO),
        clock=reloj,
        kitchen_hours=(COCINA_LUNES,),
        drafts=InMemoryDraftStore(clock=reloj),
    )
    return grafo, llm, repositorio


def _pedidos(repo: InMemoryOrderRepository) -> list[Order]:
    """Lista los pedidos del comercio de prueba.

    Args:
        repo: Repositorio en memoria.

    Returns:
        Los pedidos persistidos del tenant de prueba.
    """
    return repo.list_for_tenant(tenant_id=TENANT)


# --------------------------------------------------------------------------- understand


def test_understand_convierte_el_turno_en_propuesta() -> None:
    """La salida JSON válida se parsea y valida contra el esquema."""
    llm = _FakeLLM([JSON_PEDIR])
    estado = understand(_turno("quiero alitas y una gaseosa"), deps=_deps(llm)[0])
    assert estado["proposal"].action == "propose_order"
    assert len(estado["proposal"].items) == 2
    assert len(llm.calls) == 1


def test_understand_reintenta_si_la_salida_no_es_json() -> None:
    """Texto libre en la primera salida provoca un reintento con la corrección."""
    llm = _FakeLLM(["claro, dime qué quieres", JSON_SALUDO])
    estado = understand(_turno("hola"), deps=_deps(llm)[0])
    assert estado["proposal"].action == "reply"
    assert len(llm.calls) == 2
    correccion = llm.calls[1]["messages"][-1]
    assert isinstance(correccion, LLMMessage) and "JSON válido" in correccion.content


def test_prompt_lleva_la_hora_actual_para_el_horario_de_cocina() -> None:
    """El `system` lleva «ahora es» con el reloj del turno: el modelo no tiene reloj propio."""
    llm = _FakeLLM([JSON_MENU])
    understand(_turno("¿Qué tiene el menú?"), deps=_deps(llm)[0])
    system = llm.calls[0]["system"]
    assert isinstance(system, str)
    assert "ahora es 2026-03-02T12:00 (lunes)" in system


def test_understand_degrada_a_aclaracion_si_insiste_el_fallo() -> None:
    """Tras dos salidas inválidas el turno sigue vivo, como aclaración y sin tool."""
    llm = _FakeLLM(["no sé de qué hablas", "tampoco sé"])
    estado = understand(_turno("???"), deps=_deps(llm)[0])
    assert estado["proposal"].action == "reply"
    assert estado["proposal"].reply is not None
    assert len(llm.calls) == 2


def test_understand_rechaza_json_con_claves_de_otro_mundo() -> None:
    """El JSON con `tenant_id` (claves de más) no se acepta: degrada a aclaración."""
    llm = _FakeLLM([JSON_CON_TENANT_AJENO, JSON_CON_TENANT_AJENO])
    estado = understand(_turno("quiero alitas"), deps=_deps(llm)[0])
    assert estado["proposal"].action == "reply"
    assert len(llm.calls) == 2


# ------------------------------------------------------------------------------- validate


def test_validate_lista_lo_que_falta_para_proponer() -> None:
    """Sin ítems la propuesta queda incompleta: nada se propone con el carrito vacío."""
    propuesta = OrderProposal(action="propose_order")
    estado = validate(_turno("quiero pedir", proposal=propuesta))
    assert estado["missing_fields"] == ["items"]


def test_validate_pide_query_o_order_id_segun_la_tool() -> None:
    """Cada tool de lectura exige su parámetro obligatorio antes de ejecutarse."""
    sin_query = validate(_turno("busca", proposal=OrderProposal(action="search_products")))
    assert sin_query["missing_fields"] == ["query"]
    sin_id = validate(_turno("mi pedido", proposal=OrderProposal(action="get_order_status")))
    assert sin_id["missing_fields"] == ["order_id"]


def test_validate_sin_herramienta_no_pide_nada() -> None:
    """Una propuesta de respuesta (`reply`) o de menú no tienen datos pendientes."""
    assert validate(_turno("hola", proposal=OrderProposal(action="reply")))["missing_fields"] == []
    assert (
        validate(_turno("menú", proposal=OrderProposal(action="get_menu")))["missing_fields"] == []
    )


def test_need_more_enruta_a_pedir_datos_o_a_accionar() -> None:
    """Con faltantes se responde; completos se elige herramienta."""
    assert need_more(_turno("x", missing_fields=["items"])) == "respond"
    assert need_more(_turno("x", missing_fields=[])) == "select_action"


# -------------------------------------------------------------------------- select_action


def test_select_action_solo_acepta_tools_de_la_allowlist() -> None:
    """La allowlist coincide con el Literal de tools y es lo único que se traduce."""
    assert set(get_args(ToolName)) == ALLOWED_TOOLS
    con_tool = select_action(_turno("pedido", proposal=_propuesta_pedir(), missing_fields=[]))
    assert con_tool["tool_name"] == "propose_order"
    sin_tool = select_action(_turno("hola", proposal=OrderProposal(action="reply", reply="Hola")))
    assert "tool_name" not in sin_tool
    bloqueada = select_action(
        _turno("pedido", proposal=_propuesta_pedir(), missing_fields=["items"])
    )
    assert "tool_name" not in bloqueada


def test_ruta_tras_accion_decide_entre_tool_y_respuesta() -> None:
    """Con `tool_name` se ejecuta; sin él se responde directo (saludo/aclaración)."""
    assert ruta_tras_accion(_turno("x", tool_name="get_menu")) == "call_tool"
    assert ruta_tras_accion(_turno("x")) == "respond"


# -------------------------------------------------------------------------------- call_tool


def test_call_tool_propone_y_commitea_con_mensaje_explicito() -> None:
    """Con los nombres literales la propuesta se ejecuta y el pedido queda `ABIERTA`."""
    llm = _FakeLLM([])
    deps, repo = _deps(llm)
    estado = call_tool(
        _turno(_MSG_EXPLICITA, proposal=_propuesta_pedir(), tool_name="propose_order"),
        deps=deps,
    )
    result = estado["tool_result"]
    assert result.tool == "propose_order"
    assert result.draft_status is DraftStatus.COMMITTED
    assert result.policy is ConfirmationPolicy.AUTO
    assert "tool_error" not in estado
    pedidos = _pedidos(repo)
    assert len(pedidos) == 1
    assert pedidos[0].status == "ABIERTA"
    assert pedidos[0].total == 18_000 * 2 + 5_000


def test_call_tool_con_items_inferidos_no_escribe_nada() -> None:
    """Sin los nombres en el mensaje la política es `CONFIRM`: queda el draft, no el pedido."""
    llm = _FakeLLM([])
    deps, repo = _deps(llm)
    estado = call_tool(
        _turno(
            "quiero pedir algo para la tarde",
            proposal=_propuesta_pedir(),
            tool_name="propose_order",
        ),
        deps=deps,
    )
    result = estado["tool_result"]
    assert result.draft_status is DraftStatus.AWAITING_CONFIRMATION
    assert result.order is None
    assert result.policy_reasons == ("item_inferido:A-100", "item_inferido:P-100")
    assert _pedidos(repo) == []


def test_call_tool_convierte_el_error_de_dominio_en_tool_error() -> None:
    """Proponer un producto inexistente no rompe el turno: queda `tool_error` tipado."""
    llm = _FakeLLM([])
    deps, _ = _deps(llm)
    propuesta = OrderProposal.model_validate(
        {"action": "propose_order", "items": [{"sku": "ZZ-999", "quantity": 1}]}
    )
    estado = call_tool(
        _turno("quiero ZZ-999", proposal=propuesta, tool_name="propose_order"),
        deps=deps,
    )
    assert estado["tool_error"]["code"] == "product_unavailable"
    assert "tool_result" not in estado


def test_call_tool_sin_tool_name_reporta_no_permitida() -> None:
    """Guardia para un estado inconsistente: nada se ejecuta sin tool elegida."""
    llm = _FakeLLM([])
    deps, _ = _deps(llm)
    estado = call_tool(_turno("hola", proposal=OrderProposal(action="reply")), deps=deps)
    assert estado["tool_error"]["code"] == "tool_not_allowed"


# ----------------------------------------------------------------------- validate_result


def test_validate_result_marca_confirmacion_solo_si_el_draft_espera() -> None:
    """Solo un draft `AWAITING_CONFIRMATION` pide confirmación al cliente."""
    esperando = validate_result(
        _turno("pedido", tool_name="propose_order", tool_result=_resultado_esperando())
    )
    assert esperando["needs_confirmation"] is True
    hecho = validate_result(
        _turno("pedido", tool_name="propose_order", tool_result=_resultado_commiteado())
    )
    assert hecho["needs_confirmation"] is False
    consultando = validate_result(
        _turno("menú", tool_name="get_menu", tool_result=ToolResult(tool="get_menu"))
    )
    assert consultando["needs_confirmation"] is False
    fallido = validate_result(
        _turno("pedido", tool_name="propose_order", tool_error={"code": "minimum_not_met"})
    )
    assert fallido["needs_confirmation"] is False


def test_validate_result_rechaza_un_resultado_incoherente() -> None:
    """Si la salida no corresponde a la tool pedida no se redacta a ciegas."""
    with pytest.raises(ToolError):
        validate_result(
            _turno(
                "pedido",
                tool_name="propose_order",
                tool_result=ToolResult(tool="get_menu"),
            )
        )


def test_ruta_confirmacion_separa_las_dos_salidas() -> None:
    """La ruta condicional distingue «confirmar» de «entregar» (enganche de la Fase 4)."""
    assert ruta_confirmacion(_turno("x", needs_confirmation=True)) == "confirmar"
    assert ruta_confirmacion(_turno("x", needs_confirmation=False)) == "entregar"


# --------------------------------------------------------------------------------- respond


def test_respond_pide_los_datos_faltantes_en_el_contexto() -> None:
    """El LLM solo redacta: en el `system` van los campos que faltan, no la decisión."""
    llm = _FakeLLM(["¿Qué productos quieres y con qué cantidad?"])
    deps, _ = _deps(llm)
    estado = respond(_turno("quiero pedir", missing_fields=["items"]), deps=deps)
    assert estado["reply"] == "¿Qué productos quieres y con qué cantidad?"
    system = llm.calls[0]["system"]
    assert isinstance(system, str) and "Faltan datos" in system and "items" in system


def test_respond_pide_confirmacion_cuando_el_draft_espera() -> None:
    """El `system` incluye los datos del draft y la instrucción de no darla por hecha."""
    llm = _FakeLLM(["¿Confirmas el carrito para proceder?"])
    deps, _ = _deps(llm)
    estado = respond(
        _turno(
            "pedido",
            proposal=_propuesta_pedir(),
            tool_name="propose_order",
            tool_result=_resultado_esperando(),
            needs_confirmation=True,
        ),
        deps=deps,
    )
    system = llm.calls[0]["system"]
    assert isinstance(system, str)
    assert "awaiting_confirmation" in system and "confirme" in system
    assert estado["reply"].startswith("¿Confirmas el carrito")


def test_respond_entrega_el_resultado_ya_ejecutado() -> None:
    """Con el draft commiteado la respuesta entrega el pedido sin pedir confirmación."""
    llm = _FakeLLM(["Tu pedido ya está registrado."])
    deps, _ = _deps(llm)
    estado = respond(
        _turno(
            "pedido",
            proposal=_propuesta_pedir(),
            tool_name="propose_order",
            tool_result=_resultado_commiteado(),
            needs_confirmation=False,
        ),
        deps=deps,
    )
    system = llm.calls[0]["system"]
    assert isinstance(system, str)
    assert '"ABIERTA"' in system and "ya se ejecutó" in system
    assert estado["reply"] == "Tu pedido ya está registrado."


# ------------------------------------------------------------------------------- end-to-end


def test_e2e_saludo_responde_sin_tocar_el_legacy() -> None:
    """Saludo: el turno termina en `respond` sin tool ni escritura alguna."""
    historial = [
        LLMMessage(role="user", content="buenos días"),
        LLMMessage(role="assistant", content="Hola, ¿en qué te ayudo?"),
    ]
    grafo, llm, repo = _grafo([JSON_SALUDO, "Hola, soy el asistente de pedidos. ¿En qué te ayudo?"])
    estado = grafo.invoke({**_turno("hola"), "history": historial})
    assert estado["reply"].startswith("Hola")
    assert "tool_result" not in estado and "tool_error" not in estado
    assert _pedidos(repo) == []
    assert len(llm.calls[0]["messages"]) == 3


def test_e2e_propone_pedido_y_pide_confirmacion() -> None:
    """Ítems inferidos: se propone el draft y la respuesta pide confirmación."""
    grafo, llm, repo = _grafo([JSON_PEDIR, "¿Te confirmo el carrito para proceder?"])
    estado = grafo.invoke(_turno("Quiero pedir algo para la tarde"))
    assert estado["needs_confirmation"] is True
    assert estado["reply"] == "¿Te confirmo el carrito para proceder?"
    assert _pedidos(repo) == []
    system = llm.calls[1]["system"]
    assert isinstance(system, str) and "AÚN NO ejecutada" in system


def test_e2e_con_nombres_explicitos_ejecuta_sin_ritual() -> None:
    """Todo literal en el mensaje: `AUTO`, pedido persistido y respuesta sin confirmación."""
    grafo, llm, repo = _grafo([JSON_PEDIR, "Tu pedido ya está registrado."])
    estado = grafo.invoke(_turno(_MSG_EXPLICITA))
    assert estado["needs_confirmation"] is False
    assert estado["reply"] == "Tu pedido ya está registrado."
    pedidos = _pedidos(repo)
    assert len(pedidos) == 1 and pedidos[0].tenant_id == TENANT
    assert pedidos[0].status == "ABIERTA"
    system = llm.calls[1]["system"]
    assert isinstance(system, str) and "ya se ejecutó" in system


def test_e2e_consulta_el_menu_con_precios_reales() -> None:
    """El menú sale del catálogo con sus precios, no del modelo."""
    grafo, _, repo = _grafo([JSON_MENU, "Te comparto las bebidas del menú."])
    estado = grafo.invoke(_turno("¿Qué bebidas hay?"))
    assert estado["needs_confirmation"] is False
    assert [(p.sku, p.price) for p in estado["tool_result"].products] == [("P-100", 5_000.0)]
    assert _pedidos(repo) == []


def test_e2e_json_con_tenant_ajeno_no_ejecuta_nada() -> None:
    """Claves de más en el JSON (p. ej. `tenant_id`) no llegan ni a la tool."""
    grafo, llm, repo = _grafo(
        [JSON_CON_TENANT_AJENO, JSON_CON_TENANT_AJENO, "No entendí, ¿repites el pedido?"]
    )
    estado = grafo.invoke(_turno("quiero alitas"))
    assert estado["proposal"].action == "reply"
    assert "tool_result" not in estado
    assert _pedidos(repo) == []
    assert len(llm.calls) == 3
