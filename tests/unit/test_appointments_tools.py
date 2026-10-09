"""Tests de las tools de citas sobre dobles en memoria (Paso 5: propose/commit)."""

from datetime import datetime

import pytest

from adapters.in_memory import InMemoryDraftStore
from shared.contracts.pending import ConfirmationPolicy, DraftStatus
from shared.errors import ValidationError
from slices.appointments.application.schemas import OpeningHoursDay, ToolResult
from slices.appointments.application.tools import AppointmentTools
from slices.appointments.domain.errors import (
    IncompleteAppointmentData,
    OutsideOpeningHours,
    SlotUnavailable,
    TenantMismatch,
)
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Otro_Comercio_01"
CONVERSACION = "whatsapp:57300111111"

LUNES = OpeningHoursDay(weekday=0, open_time="09:00", close_time="12:00")
LUNES_2026_03_02 = "2026-03-02"
MARTES_2026_03_03 = "2026-03-03"
# Mensaje con los cuatro datos literales: la política puede ir a `AUTO`.
_MSG_EXPLICITA = "cita 2026-03-02 10:00 Ana Pérez 3001112233"


class _RelojFijo:
    """Reloj inyectable con hora fija: decide qué huecos se consideran pasados."""

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


def _tools(
    *,
    ahora: datetime = datetime(2026, 3, 2, 8, 0),
    horario: tuple[OpeningHoursDay, ...] = (LUNES,),
    repo: InMemoryAppointmentRepository | None = None,
) -> tuple[AppointmentTools, InMemoryAppointmentRepository, InMemoryDraftStore]:
    """Construye las tools con dobles en memoria y un horario de lunes.

    Args:
        ahora: Hora del reloj fijo.
        horario: Horario de atención inyectado.
        repo: Repositorio reutilizable entre tools (para encadenar creaciones).

    Returns:
        Tupla con las tools, su repositorio y el store de drafts, para asertar sobre
        lo persistido en ambos.
    """
    repositorio = repo if repo is not None else InMemoryAppointmentRepository()
    reloj = _RelojFijo(ahora)
    drafts = InMemoryDraftStore(clock=reloj)
    tools = AppointmentTools(repo=repositorio, clock=reloj, opening_hours=horario, drafts=drafts)
    return tools, repositorio, drafts


def _proponer(
    tools: AppointmentTools,
    *,
    date: str = LUNES_2026_03_02,
    time: str = "10:00",
    customer_name: str = "Ana Pérez",
    contact: str = "3001112233",
    message: str = _MSG_EXPLICITA,
    correlation_id: str = "corr-1",
) -> ToolResult:
    """Propone una cita con la firma real de la tool.

    Args:
        tools: Tools bajo prueba.
        date: Fecha de la cita.
        time: Hora de la cita.
        customer_name: Nombre del cliente.
        contact: Contacto del cliente.
        message: Mensaje crudo (decide qué campos se dan por dichos).
        correlation_id: Idempotencia de la propuesta.

    Returns:
        El `ToolResult` de la propuesta.
    """
    return tools.propose_appointment(
        tenant_id=TENANT,
        correlation_id=correlation_id,
        conversation_id=CONVERSACION,
        message=message,
        date=date,
        time=time,
        customer_name=customer_name,
        contact=contact,
    )


def _huecos(tools: AppointmentTools, date: str, *, tenant_id: str = TENANT) -> list[str]:
    """Consulta la disponibilidad y devuelve solo las horas de inicio.

    Args:
        tools: Tools bajo prueba.
        date: Día a consultar.
        tenant_id: Comercio.

    Returns:
        Las horas (`HH:MM`) de cada hueco libre, en orden.
    """
    result = tools.get_availability(tenant_id=tenant_id, date=date, party_size=2)
    return [slot.start.strftime("%H:%M") for slot in result.slots]


def test_disponibilidad_ofrece_todos_los_huecos_del_horario() -> None:
    """Un lunes laborable con la mañana libre devuelve los tres huecos de una hora."""
    tools, _, _ = _tools()
    assert _huecos(tools, LUNES_2026_03_02) == ["09:00", "10:00", "11:00"]


def test_disponibilidad_descarta_los_huecos_ya_pasados() -> None:
    """Con el reloj a las 10:30 solo queda el hueco de las 11:00."""
    tools, _, _ = _tools(ahora=datetime(2026, 3, 2, 10, 30))
    assert _huecos(tools, LUNES_2026_03_02) == ["11:00"]


def test_disponibilidad_descarta_el_hueco_ocupado() -> None:
    """Una cita existente a las 10:00 quita ese hueco del listado."""
    tools, _, _ = _tools()
    _proponer(tools, correlation_id="corr-ocupada")
    assert _huecos(tools, LUNES_2026_03_02) == ["09:00", "11:00"]


def test_disponibilidad_sin_horario_o_sin_dia_devuelve_vacio() -> None:
    """Sin horario inyectado, o en un día no laborable, no se promete nada."""
    tools_sin_horario, _, _ = _tools(horario=())
    assert _huecos(tools_sin_horario, LUNES_2026_03_02) == []
    tools_lunes, _, _ = _tools()
    assert _huecos(tools_lunes, MARTES_2026_03_03) == []


def test_disponibilidad_con_fecha_invalida_es_error() -> None:
    """Una fecha no ISO es error del llamador, no una lista vacía silenciosa."""
    tools, _, _ = _tools()
    with pytest.raises(ValidationError):
        tools.get_availability(tenant_id=TENANT, date="mañana", party_size=None)


def test_propuesta_con_datos_explicitos_se_commitea_auto() -> None:
    """Con los cuatro datos literales en el mensaje la política es `AUTO` y se ejecuta."""
    tools, repo, drafts = _tools()
    result = _proponer(tools)
    assert result.appointment is not None
    assert result.appointment.status == "confirmed"
    assert result.policy is ConfirmationPolicy.AUTO
    assert result.draft_status is DraftStatus.COMMITTED
    assert result.draft_id is not None
    guardada = repo.find(tenant_id=TENANT, appointment_id=result.appointment.id)
    assert guardada is not None and guardada.starts_at == datetime(2026, 3, 2, 10, 0)
    draft = drafts.get(tenant_id=TENANT, draft_id=result.draft_id)
    assert draft is not None and draft.undo_until is not None


def test_propuesta_con_campos_inferidos_queda_a_la_espera() -> None:
    """Si el modelo infirió datos (nombre/contacto) la política exige `CONFIRM`."""
    tools, repo, drafts = _tools()
    result = _proponer(
        tools,
        message="quiero cita el lunes a las 10 con Ana",
        correlation_id="corr-inferida",
    )
    assert result.appointment is None
    assert result.policy is ConfirmationPolicy.CONFIRM
    assert result.draft_status is DraftStatus.AWAITING_CONFIRMATION
    assert "campo_inferido:contact" in result.policy_reasons
    assert (
        repo.list_for_period(
            tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
        )
        == []
    )
    draft = drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION)
    assert draft is not None and draft.status is DraftStatus.AWAITING_CONFIRMATION


def test_propuesta_sin_datos_minimos_no_persiste() -> None:
    """Sin nombre y contacto la tool rechaza con el detalle de lo que falta (regla 4)."""
    tools, repo, _ = _tools()
    with pytest.raises(IncompleteAppointmentData) as excinfo:
        _proponer(tools, customer_name="", contact="")
    assert excinfo.value.details["faltan"] == "customer_name,contact"
    assert (
        repo.list_for_period(
            tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
        )
        == []
    )


def test_propuesta_es_idempotente_por_correlation_id() -> None:
    """Repetir la misma petición devuelve el mismo draft y no duplica la cita."""
    tools, repo, _ = _tools()
    primera = _proponer(tools, correlation_id="corr-reintento")
    segunda = _proponer(tools, correlation_id="corr-reintento")
    assert primera.draft_id == segunda.draft_id
    assert primera.appointment is not None and segunda.appointment is not None
    assert primera.appointment.id == segunda.appointment.id
    assert (
        len(
            repo.list_for_period(
                tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
            )
        )
        == 1
    )


def test_propuesta_sobre_turno_ocupado_se_rechaza() -> None:
    """La regla 2: otro cliente no puede proponer el mismo turno (sin draft nuevo)."""
    tools, repo, _ = _tools()
    _proponer(tools, correlation_id="corr-primera")
    with pytest.raises(SlotUnavailable) as excinfo:
        _proponer(
            tools,
            message="cita 2026-03-02 10:00 Otro Cliente 3009998877",
            correlation_id="corr-segunda",
        )
    assert "ocupada_inicio" in excinfo.value.details
    assert (
        len(
            repo.list_for_period(
                tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
            )
        )
        == 1
    )


def test_propuesta_fuera_del_horario_se_rechaza() -> None:
    """La regla 3: ni un día sin franja ni una hora fuera del horario pasan."""
    tools, _, _ = _tools()
    with pytest.raises(OutsideOpeningHours):
        _proponer(tools, date=MARTES_2026_03_03)
    with pytest.raises(OutsideOpeningHours):
        _proponer(tools, time="13:00", correlation_id="corr-tarde")


def test_propuesta_de_un_turno_pasado_se_rechaza() -> None:
    """Antes que el horario se comprueba que el turno no esté en el pasado."""
    tools, _, _ = _tools()
    with pytest.raises(SlotUnavailable) as excinfo:
        _proponer(tools, time="07:00")
    assert excinfo.value.details["motivo"] == "pasado"


def test_cancelar_con_el_id_en_el_seguimiento_se_commitea_auto() -> None:
    """Con el id literal en el mensaje la cancelación se ejecuta con deshacer."""
    tools, repo, drafts = _tools()
    creada = _proponer(tools).appointment
    assert creada is not None
    result = tools.cancel_appointment(
        tenant_id=TENANT,
        correlation_id="corr-cancel",
        conversation_id=CONVERSACION,
        message=f"cancela la cita {creada.id}",
        appointment_id=creada.id,
    )
    assert result.cancelled_id == creada.id
    assert result.draft_status is DraftStatus.COMMITTED
    guardada = repo.find(tenant_id=TENANT, appointment_id=creada.id)
    assert guardada is not None and guardada.status == "cancelled"
    assert drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION) is None


def test_cancelar_sin_el_id_literal_queda_a_la_espera() -> None:
    """Si el id no aparece en el mensaje, la cancelación pide confirmación primero."""
    tools, repo, drafts = _tools()
    creada = _proponer(tools).appointment
    assert creada is not None
    result = tools.cancel_appointment(
        tenant_id=TENANT,
        correlation_id="corr-cancel-espera",
        conversation_id=CONVERSACION,
        message="cancela mi cita del lunes",
        appointment_id=creada.id,
    )
    assert result.cancelled_id is None
    assert result.draft_status is DraftStatus.AWAITING_CONFIRMATION
    guardada = repo.find(tenant_id=TENANT, appointment_id=creada.id)
    assert guardada is not None and guardada.status == "confirmed"
    draft = drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION)
    assert draft is not None and draft.payload["op"] == "cancel"


def test_cancelar_una_cita_ya_cancelada_es_idempotente() -> None:
    """Repetir la cancelación no crea draft nuevo ni toca nada más."""
    tools, _, drafts = _tools()
    creada = _proponer(tools).appointment
    assert creada is not None
    tools.cancel_appointment(
        tenant_id=TENANT,
        correlation_id="corr-cancel-1",
        conversation_id=CONVERSACION,
        message=f"cancela {creada.id}",
        appointment_id=creada.id,
    )
    repetida = tools.cancel_appointment(
        tenant_id=TENANT,
        correlation_id="corr-cancel-2",
        conversation_id=CONVERSACION,
        message="cancela otra vez",
        appointment_id=creada.id,
    )
    assert repetida.cancelled_id == creada.id
    assert repetida.draft_id is None
    assert drafts.get_active(tenant_id=TENANT, conversation_id=CONVERSACION) is None


def test_cancelar_cita_inexistente_o_de_otro_comercio_es_rechazo_generico() -> None:
    """Nunca se confirma que una cita exista en otro comercio: mismo error que «no existe»."""
    tools, _, _ = _tools()
    with pytest.raises(TenantMismatch):
        tools.cancel_appointment(
            tenant_id=TENANT,
            correlation_id="corr-x",
            conversation_id=CONVERSACION,
            message="cancela no-existe",
            appointment_id="no-existe",
        )
    with pytest.raises(TenantMismatch):
        tools.cancel_appointment(
            tenant_id=OTRO_TENANT,
            correlation_id="corr-x",
            conversation_id=CONVERSACION,
            message="cancela no-existe",
            appointment_id="no-existe",
        )


def test_horario_de_atencion_sale_de_la_tool() -> None:
    """La tool devuelve exactamente el horario inyectado (nada lo inventa el LLM)."""
    tools, _, _ = _tools()
    result = tools.get_opening_hours(tenant_id=TENANT)
    assert result.hours == [LUNES]


def test_ninguna_tool_trabaja_sin_comercio() -> None:
    """Un `tenant_id` vacío se rechaza en las cuatro tools (regla 1)."""
    tools, _, _ = _tools()
    with pytest.raises(ValidationError):
        tools.get_availability(tenant_id="", date=LUNES_2026_03_02, party_size=None)
    with pytest.raises(ValidationError):
        tools.get_opening_hours(tenant_id="")
    with pytest.raises(ValidationError):
        tools.cancel_appointment(
            tenant_id="",
            correlation_id="corr-1",
            conversation_id=CONVERSACION,
            message="cancela c-1",
            appointment_id="c-1",
        )
    with pytest.raises(ValidationError):
        tools.propose_appointment(
            tenant_id="",
            correlation_id="corr-1",
            conversation_id=CONVERSACION,
            message=_MSG_EXPLICITA,
            date=LUNES_2026_03_02,
            time="10:00",
            customer_name="Ana Pérez",
            contact="3001112233",
        )
