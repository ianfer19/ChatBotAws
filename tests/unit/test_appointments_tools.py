"""Tests de las cuatro tools de citas sobre dobles en memoria (Paso 3)."""

from datetime import datetime

import pytest

from shared.errors import ValidationError
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.application.tools import AppointmentTools
from slices.appointments.domain.errors import IncompleteAppointmentData, TenantMismatch
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Otro_Comercio_01"

LUNES = OpeningHoursDay(weekday=0, open_time="09:00", close_time="12:00")
LUNES_2026_03_02 = "2026-03-02"
JUEVES_2026_03_05 = "2026-03-05"


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
) -> tuple[AppointmentTools, InMemoryAppointmentRepository]:
    """Construye las tools con dobles en memoria y un horario de lunes.

    Args:
        ahora: Hora del reloj fijo.
        horario: Horario de atención inyectado.
        repo: Repositorio reutilizable entre tools (para encadenar creaciones).

    Returns:
        Tupla con las tools y su repositorio, para asertar sobre lo persistido.
    """
    repositorio = repo if repo is not None else InMemoryAppointmentRepository()
    tools = AppointmentTools(repo=repositorio, clock=_RelojFijo(ahora), opening_hours=horario)
    return tools, repositorio


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
    tools, _ = _tools()
    assert _huecos(tools, LUNES_2026_03_02) == ["09:00", "10:00", "11:00"]


def test_disponibilidad_descarta_los_huecos_ya_pasados() -> None:
    """Con el reloj a las 10:30 solo queda el hueco de las 11:00."""
    tools, _ = _tools(ahora=datetime(2026, 3, 2, 10, 30))
    assert _huecos(tools, LUNES_2026_03_02) == ["11:00"]


def test_disponibilidad_descarta_el_hueco_ocupado() -> None:
    """Una cita existente a las 10:00 quita ese hueco del listado."""
    tools, _ = _tools()
    tools.create_appointment(
        tenant_id=TENANT,
        correlation_id="corr-ocupada",
        date=LUNES_2026_03_02,
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )
    assert _huecos(tools, LUNES_2026_03_02) == ["09:00", "11:00"]


def test_disponibilidad_sin_horario_o_sin_dia_devuelve_vacio() -> None:
    """Sin horario inyectado, o en un día no laborable, no se promete nada."""
    tools_sin_horario, _ = _tools(horario=())
    assert _huecos(tools_sin_horario, LUNES_2026_03_02) == []
    tools_lunes, _ = _tools()
    assert _huecos(tools_lunes, "2026-03-03") == []


def test_disponibilidad_con_fecha_invalida_es_error() -> None:
    """Una fecha no ISO es error del llamador, no una lista vacía silenciosa."""
    tools, _ = _tools()
    with pytest.raises(ValidationError):
        tools.get_availability(tenant_id=TENANT, date="mañana", party_size=None)


def test_crear_cita_completa_persiste_en_el_comercio() -> None:
    """La cita se guarda con estado `pending` y el inicio pedido."""
    tools, repo = _tools()
    result = tools.create_appointment(
        tenant_id=TENANT,
        correlation_id="corr-1",
        date=JUEVES_2026_03_05,
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )
    assert result.appointment is not None
    assert result.appointment.status == "pending"
    guardada = repo.find(tenant_id=TENANT, appointment_id=result.appointment.id)
    assert guardada is not None and guardada.starts_at == datetime(2026, 3, 5, 10, 0)


def test_crear_cita_sin_datos_minimos_no_persiste() -> None:
    """Sin nombre y contacto la tool rechaza con el detalle de lo que falta (regla 4)."""
    tools, repo = _tools()
    with pytest.raises(IncompleteAppointmentData) as excinfo:
        tools.create_appointment(
            tenant_id=TENANT,
            correlation_id="corr-1",
            date=JUEVES_2026_03_05,
            time="10:00",
            customer_name="",
            contact="",
        )
    assert excinfo.value.details["faltan"] == "customer_name,contact"
    assert (
        repo.list_for_period(
            tenant_id=TENANT, start=datetime(2026, 1, 1), end=datetime(2026, 12, 31)
        )
        == []
    )


def test_crear_cita_es_idempotente_por_correlation_id() -> None:
    """Repetir la misma petición devuelve la cita ya guardada, sin duplicar."""
    tools, repo = _tools()
    kwargs = {
        "tenant_id": TENANT,
        "correlation_id": "corr-reintento",
        "date": JUEVES_2026_03_05,
        "time": "11:00",
        "customer_name": "Ana Pérez",
        "contact": "3001112233",
    }
    primera = tools.create_appointment(**kwargs)
    segunda = tools.create_appointment(**kwargs)
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


def test_cancelar_cita_existente_de_este_comercio() -> None:
    """La cancelación marca la cita como `cancelled` y devuelve su identificador."""
    tools, repo = _tools()
    creada = tools.create_appointment(
        tenant_id=TENANT,
        correlation_id="corr-1",
        date=JUEVES_2026_03_05,
        time="10:00",
        customer_name="Ana Pérez",
        contact="3001112233",
    )
    assert creada.appointment is not None
    result = tools.cancel_appointment(tenant_id=TENANT, appointment_id=creada.appointment.id)
    assert result.cancelled_id == creada.appointment.id
    guardada = repo.find(tenant_id=TENANT, appointment_id=creada.appointment.id)
    assert guardada is not None and guardada.status == "cancelled"


def test_cancelar_cita_inexistente_o_de_otro_comercio_es_rechazo_generico() -> None:
    """Nunca se confirma que una cita exista en otro comercio: mismo error que «no existe»."""
    tools, _ = _tools()
    with pytest.raises(TenantMismatch):
        tools.cancel_appointment(tenant_id=TENANT, appointment_id="no-existe")
    with pytest.raises(TenantMismatch):
        tools.cancel_appointment(tenant_id=OTRO_TENANT, appointment_id="no-existe")


def test_horario_de_atencion_sale_de_la_tool() -> None:
    """La tool devuelve exactamente el horario inyectado (nada lo inventa el LLM)."""
    tools, _ = _tools()
    result = tools.get_opening_hours(tenant_id=TENANT)
    assert result.hours == [LUNES]


def test_ninguna_tool_trabaja_sin_comercio() -> None:
    """Un `tenant_id` vacío se rechaza en las cuatro tools (regla 1)."""
    tools, _ = _tools()
    with pytest.raises(ValidationError):
        tools.get_availability(tenant_id="", date=LUNES_2026_03_02, party_size=None)
    with pytest.raises(ValidationError):
        tools.get_opening_hours(tenant_id="")
    with pytest.raises(ValidationError):
        tools.cancel_appointment(tenant_id="", appointment_id="c-1")
    with pytest.raises(ValidationError):
        tools.create_appointment(
            tenant_id="",
            correlation_id="corr-1",
            date=JUEVES_2026_03_05,
            time="10:00",
            customer_name="Ana Pérez",
            contact="3001112233",
        )
