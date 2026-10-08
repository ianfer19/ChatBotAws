"""Tests de los nodos y del grafo end-to-end de citas (ROADMAP Paso 3)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, get_args

import pytest

from shared.errors import ToolError
from shared.ports import LLMMessage, LLMResult
from slices.appointments.application.deps import Deps
from slices.appointments.application.graph import build_appointment_graph
from slices.appointments.application.nodes import (
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
from slices.appointments.application.nodes.select_action import ALLOWED_TOOLS
from slices.appointments.application.schemas import (
    AppointmentProposal,
    AppointmentView,
    OpeningHoursDay,
    ToolName,
    ToolResult,
)
from slices.appointments.application.state import AgentState
from slices.appointments.application.tools import AppointmentTools
from slices.appointments.domain.entities import Appointment
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository

TENANT = "Sede_Elite_01"
LUNES = OpeningHoursDay(weekday=0, open_time="09:00", close_time="12:00")
LUNES_2026_03_02 = "2026-03-02"
JUEVES_2026_03_05 = "2026-03-05"

JSON_CREAR = (
    '{"action": "create_appointment", "date": "2026-03-05", "time": "10:00", '
    '"customer_name": "Ana Pérez", "contact": "3001112233", '
    '"appointment_id": null, "party_size": null, "reply": null}'
)
JSON_CONSULTAR = (
    '{"action": "get_availability", "date": "2026-03-02", "time": null, '
    '"customer_name": null, "contact": null, "appointment_id": null, '
    '"party_size": 2, "reply": null}'
)
JSON_SALUDO = (
    '{"action": "reply", "date": null, "time": null, "customer_name": null, '
    '"contact": null, "appointment_id": null, "party_size": null, '
    '"reply": "Hola, soy el asistente de citas."}'
)
JSON_CON_TENANT_AJENO = (
    '{"action": "create_appointment", "date": "2026-03-05", "time": "10:00", '
    '"customer_name": "Ana Pérez", "contact": "3001112233", '
    '"appointment_id": null, "party_size": null, "reply": null, '
    '"tenant_id": "Comercio_Ajeno_99"}'
)


class _RelojFijo:
    """Reloj inyectable con hora fija para que la disponibilidad sea estable."""

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
    proposal: AppointmentProposal | None = None,
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
    estado = AgentState(tenant_id=TENANT, correlation_id=correlation_id, user_message=mensaje)
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
    repo: InMemoryAppointmentRepository | None = None,
) -> tuple[Deps, InMemoryAppointmentRepository]:
    """Construye las dependencias de los nodos con dobles en memoria.

    Args:
        llm: Doble guionizado del modelo.
        repo: Repositorio reutilizable entre nodos.

    Returns:
        Tupla con las dependencias y su repositorio.
    """
    repositorio = repo if repo is not None else InMemoryAppointmentRepository()
    deps = Deps(
        llm=llm,
        tools=AppointmentTools(
            repo=repositorio,
            clock=_RelojFijo(datetime(2026, 3, 2, 8, 0)),
            opening_hours=(LUNES,),
        ),
    )
    return deps, repositorio


def _propuesta_crear() -> AppointmentProposal:
    """Propuesta completa de creación (sin datos faltantes).

    Returns:
        Propuesta validada con todos los datos mínimos.
    """
    return AppointmentProposal(
        action="create_appointment",
        date=JUEVES_2026_03_05,
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )


def _resultado_creada() -> ToolResult:
    """Salida de `create_appointment` como la dejaría la tool real.

    Returns:
        `ToolResult` con la vista de la cita creada.
    """
    return ToolResult(
        tool="create_appointment",
        appointment=AppointmentView(
            id="appt-1",
            starts_at=datetime(2026, 3, 5, 10, 0),
            customer_name="Ana Pérez",
            status="pending",
        ),
    )


def _grafo(
    salidas: list[str],
    *,
    repo: InMemoryAppointmentRepository | None = None,
) -> tuple[Any, _FakeLLM, InMemoryAppointmentRepository]:
    """Grafo compilado con LLM guionizado y dobles en memoria.

    Args:
        salidas: Textos que devolverá el LLM, uno por invocación.
        repo: Repositorio reutilizable para asertar sobre lo persistido.

    Returns:
        Tupla con el grafo, el doble de LLM y el repositorio.
    """
    llm = _FakeLLM(salidas)
    repositorio = repo if repo is not None else InMemoryAppointmentRepository()
    grafo = build_appointment_graph(
        llm=llm,
        repo=repositorio,
        clock=_RelojFijo(datetime(2026, 3, 2, 8, 0)),
        opening_hours=(LUNES,),
    )
    return grafo, llm, repositorio


def _citas(repo: InMemoryAppointmentRepository) -> list[Appointment]:
    """Lista todas las citas del comercio de prueba en 2026.

    Args:
        repo: Repositorio en memoria.

    Returns:
        Las citas persistidas del tenant de prueba.
    """
    return list(
        repo.list_for_period(
            tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
        )
    )


# --------------------------------------------------------------------------- understand


def test_understand_convierte_el_turno_en_propuesta() -> None:
    """La salida JSON válida se parsea y valida contra el esquema."""
    llm = _FakeLLM([JSON_CREAR])
    estado = understand(_turno("quiero una cita el 5 de marzo"), deps=_deps(llm)[0])
    assert estado["proposal"].action == "create_appointment"
    assert estado["proposal"].date == JUEVES_2026_03_05
    assert len(llm.calls) == 1


def test_understand_reintenta_si_la_salida_no_es_json() -> None:
    """Texto libre en la primera salida provoca un reintento con la corrección."""
    llm = _FakeLLM(["claro, dime la fecha", JSON_SALUDO])
    estado = understand(_turno("hola"), deps=_deps(llm)[0])
    assert estado["proposal"].action == "reply"
    assert len(llm.calls) == 2
    correccion = llm.calls[1]["messages"][-1]
    assert isinstance(correccion, LLMMessage) and "JSON válido" in correccion.content


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
    estado = understand(_turno("cita para mañana"), deps=_deps(llm)[0])
    assert estado["proposal"].action == "reply"
    assert len(llm.calls) == 2


# ------------------------------------------------------------------------------- validate


def test_validate_lista_lo_que_falta_para_crear() -> None:
    """Sin contacto la propuesta queda incompleta (regla 4)."""
    propuesta = AppointmentProposal(
        action="create_appointment",
        date=JUEVES_2026_03_05,
        time="10:00",
        customer_name="Ana Pérez",
    )
    estado = validate(_turno("cita", proposal=propuesta))
    assert estado["missing_fields"] == ["contact"]


def test_validate_sin_herramienta_no_pide_nada() -> None:
    """Una propuesta de respuesta (`reply`) no tiene datos pendientes."""
    propuesta = AppointmentProposal(action="reply", reply="Hola")
    estado = validate(_turno("hola", proposal=propuesta))
    assert estado["missing_fields"] == []


def test_need_more_enruta_a_pedir_datos_o_a_accionar() -> None:
    """Con faltantes se responde; completos se elige herramienta."""
    assert need_more(_turno("x", missing_fields=["date"])) == "respond"
    assert need_more(_turno("x", missing_fields=[])) == "select_action"


# -------------------------------------------------------------------------- select_action


def test_select_action_solo_acepta_tools_de_la_allowlist() -> None:
    """La allowlist coincide con el Literal de tools y es lo único que se traduce."""
    assert set(get_args(ToolName)) == ALLOWED_TOOLS
    con_tool = select_action(_turno("cita", proposal=_propuesta_crear(), missing_fields=[]))
    assert con_tool["tool_name"] == "create_appointment"
    sin_tool = select_action(
        _turno("hola", proposal=AppointmentProposal(action="reply", reply="Hola"))
    )
    assert "tool_name" not in sin_tool
    bloqueada = select_action(
        _turno("cita", proposal=_propuesta_crear(), missing_fields=["contact"])
    )
    assert "tool_name" not in bloqueada


def test_ruta_tras_accion_decide_entre_tool_y_respuesta() -> None:
    """Con `tool_name` se ejecuta; sin él se responde directo (saludo/aclaración)."""
    assert ruta_tras_accion(_turno("x", tool_name="get_opening_hours")) == "call_tool"
    assert ruta_tras_accion(_turno("x")) == "respond"


# -------------------------------------------------------------------------------- call_tool


def test_call_tool_crea_la_cita_y_la_persiste() -> None:
    """La tool elegida recibe el `proposal` y el contexto, y deja el resultado."""
    llm = _FakeLLM([])
    deps, repo = _deps(llm)
    estado = call_tool(
        _turno("cita", proposal=_propuesta_crear(), tool_name="create_appointment"),
        deps=deps,
    )
    assert estado["tool_result"].tool == "create_appointment"
    assert "tool_error" not in estado
    assert len(_citas(repo)) == 1


def test_call_tool_convierte_el_error_de_dominio_en_tool_error() -> None:
    """Cancelar algo que no existe no rompe el turno: queda como `tool_error` tipado."""
    llm = _FakeLLM([])
    deps, _ = _deps(llm)
    propuesta = AppointmentProposal(action="cancel_appointment", appointment_id="no-existe")
    estado = call_tool(
        _turno("cancela", proposal=propuesta, tool_name="cancel_appointment"),
        deps=deps,
    )
    assert estado["tool_error"]["code"] == "tenant_mismatch"
    assert "tool_result" not in estado


def test_call_tool_sin_tool_name_reporta_no_permitida() -> None:
    """Guardia para un estado inconsistente: nada se ejecuta sin tool elegida."""
    llm = _FakeLLM([])
    deps, _ = _deps(llm)
    estado = call_tool(_turno("hola", proposal=AppointmentProposal(action="reply")), deps=deps)
    assert estado["tool_error"]["code"] == "tool_not_allowed"


# ----------------------------------------------------------------------- validate_result


def test_validate_result_marca_confirmacion_solo_si_toca() -> None:
    """Crear o cancelar piden confirmación; una consulta no."""
    creando = validate_result(
        _turno(
            "cita",
            tool_name="create_appointment",
            tool_result=_resultado_creada(),
        )
    )
    assert creando["needs_confirmation"] is True
    consultando = validate_result(
        _turno(
            "horario",
            tool_name="get_opening_hours",
            tool_result=ToolResult(tool="get_opening_hours"),
        )
    )
    assert consultando["needs_confirmation"] is False
    fallido = validate_result(
        _turno("cancela", tool_name="cancel_appointment", tool_error={"code": "tenant_mismatch"})
    )
    assert fallido["needs_confirmation"] is False


def test_validate_result_rechaza_un_resultado_incoherente() -> None:
    """Si la salida no corresponde a la tool pedida no se redacta a ciegas."""
    with pytest.raises(ToolError):
        validate_result(
            _turno(
                "cita",
                tool_name="create_appointment",
                tool_result=ToolResult(tool="get_opening_hours"),
            )
        )


def test_ruta_confirmacion_separa_las_dos_salidas() -> None:
    """La ruta condicional distingue «confirmar» de «entregar» (enganche del Paso 8)."""
    assert ruta_confirmacion(_turno("x", needs_confirmation=True)) == "confirmar"
    assert ruta_confirmacion(_turno("x", needs_confirmation=False)) == "entregar"


# --------------------------------------------------------------------------------- respond


def test_respond_pide_los_datos_faltantes_en_el_contexto() -> None:
    """El LLM solo redacta: en el `system` van los campos que faltan, no la decisión."""
    llm = _FakeLLM(["¿Me confirmas tu contacto?"])
    deps, _ = _deps(llm)
    estado = respond(_turno("cita", missing_fields=["contact"]), deps=deps)
    assert estado["reply"] == "¿Me confirmas tu contacto?"
    system = llm.calls[0]["system"]
    assert isinstance(system, str) and "Faltan datos" in system and "contact" in system


def test_respond_entrega_el_resultado_como_datos() -> None:
    """El `system` incluye el JSON del resultado y la instrucción de confirmación."""
    llm = _FakeLLM(["Tu cita está registrada, ¿la confirmas?"])
    deps, _ = _deps(llm)
    estado = respond(
        _turno(
            "cita",
            proposal=_propuesta_crear(),
            tool_name="create_appointment",
            tool_result=_resultado_creada(),
            needs_confirmation=True,
        ),
        deps=deps,
    )
    system = llm.calls[0]["system"]
    assert isinstance(system, str)
    assert "2026-03-05T10:00:00" in system and "confirmación" in system
    assert estado["reply"] == "Tu cita está registrada, ¿la confirmas?"


# ------------------------------------------------------------------------------- end-to-end


def test_e2e_saludo_responde_sin_tocar_el_repositorio() -> None:
    """Saludo: el turno termina en `respond` sin tool ni escritura alguna."""
    historial = [
        LLMMessage(role="user", content="buenos días"),
        LLMMessage(role="assistant", content="Hola, ¿en qué te ayudo?"),
    ]
    grafo, llm, repo = _grafo([JSON_SALUDO, "Hola, soy el asistente de citas. ¿En qué te ayudo?"])
    estado = grafo.invoke({**_turno("hola"), "history": historial})
    assert estado["reply"].startswith("Hola")
    assert "tool_result" not in estado and "tool_error" not in estado
    assert _citas(repo) == []
    assert len(llm.calls[0]["messages"]) == 3


def test_e2e_crea_cita_y_pide_confirmacion() -> None:
    """Con datos completos se crea la cita, se persiste y se pide confirmación."""
    grafo, llm, repo = _grafo([JSON_CREAR, "Tu cita del 5 de marzo a las 10:00 está lista."])
    estado = grafo.invoke(_turno("Quiero cita el 5 de marzo a las 10:00 con Ana"))
    assert estado["needs_confirmation"] is True
    assert estado["reply"] == "Tu cita del 5 de marzo a las 10:00 está lista."
    citas = _citas(repo)
    assert len(citas) == 1 and citas[0].tenant_id == TENANT
    system = llm.calls[1]["system"]
    assert isinstance(system, str) and "2026-03-05T10:00:00" in system


def test_e2e_consulta_disponibilidad_con_huecos_reales() -> None:
    """La disponibilidad sale del repositorio y el horario, no del modelo."""
    grafo, _, repo = _grafo([JSON_CONSULTAR, "Tengo libre de 9 a 12 el lunes."])
    estado = grafo.invoke(_turno("¿Qué huecos hay el lunes?"))
    assert estado["needs_confirmation"] is False
    assert len(estado["tool_result"].slots) == 3
    assert _citas(repo) == []


def test_e2e_json_con_tenant_ajeno_no_ejecuta_nada() -> None:
    """Claves de más en el JSON (p. ej. `tenant_id`) no llegan ni a la tool."""
    grafo, llm, repo = _grafo(
        [JSON_CON_TENANT_AJENO, JSON_CON_TENANT_AJENO, "No entendí, ¿repites la cita?"]
    )
    estado = grafo.invoke(_turno("cita el 5 de marzo"))
    assert estado["proposal"].action == "reply"
    assert "tool_result" not in estado
    assert _citas(repo) == []
    assert len(llm.calls) == 3
