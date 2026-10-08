"""Las cuatro tools del agente de citas, sobre puertos inyectados (Paso 3: fakes).

Ninguna tool acepta el comercio del LLM: el `tenant_id` siempre llega del estado del
turno (contexto resuelto en el gateway), igual que en los ports. La disponibilidad se
calcula aquí a partir del repositorio y del horario inyectado — el modelo solo redacta.

`TODO(decision)`: reglas de solape (2) y horario (3), estados canónicos de la cita y
confirmación previa (HITL) llegan con el Paso 5/8; hoy `create_appointment` guarda con
estado `pending`. `TODO(decision)`: convención de zona horaria (fechas locales naive vs
UTC) al conectar Aurora en el Paso 6, para que reloj, huecos y citas compartan criterio.
"""

import uuid
from collections.abc import Sequence
from datetime import date as Date
from datetime import datetime, timedelta
from datetime import time as Time

from shared.errors import ValidationError
from shared.ports import ClockPort
from slices.appointments.application.schemas import (
    AppointmentView,
    OpeningHoursDay,
    Slot,
    ToolResult,
)
from slices.appointments.domain.entities import Appointment
from slices.appointments.domain.errors import IncompleteAppointmentData, TenantMismatch
from slices.appointments.domain.ports import AppointmentRepositoryPort
from slices.appointments.domain.rules import missing_appointment_fields

_DURACION_HUECO = timedelta(hours=1)
"""Duración fija de cada hueco mientras no exista configuración por comercio (Paso 5)."""


def _require_tenant(tenant_id: str) -> None:
    """Rechaza operaciones sin comercio: ninguna tool trabaja «a ciegas».

    Args:
        tenant_id: Comercio resuelto en el gateway.

    Raises:
        ValidationError: Si `tenant_id` está vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en las tools de citas")


def _vista(appointment: Appointment) -> AppointmentView:
    """Convierte una cita del dominio en la vista que consume el prompt de redacción.

    Args:
        appointment: Cita ya persistida.

    Returns:
        Vista inmutable con los campos seguros de mostrar.
    """
    return AppointmentView(
        id=appointment.id,
        starts_at=appointment.starts_at,
        customer_name=appointment.customer_name,
        status=appointment.status,
    )


def _es_comparable(ahora: datetime, momento: datetime) -> bool:
    """Indica si dos fechas se pueden comparar (ambas con o sin zona horaria).

    Args:
        ahora: Instante del reloj inyectado.
        momento: Instante generado por la tool.

    Returns:
        `True` si ambas son naive o ambas son aware; `False` en caso contrario.
    """
    return (ahora.tzinfo is None) == (momento.tzinfo is None)


class AppointmentTools:
    """Implementación de `get_availability`, `create_appointment`, `cancel_appointment`
    y `get_opening_hours` contra el repositorio y el horario inyectados.

    Example:
        >>> tools = AppointmentTools(repo=repositorio, clock=reloj, opening_hours=[])
        >>> tools.get_opening_hours(tenant_id="Sede_Elite_01").hours
        []
    """

    def __init__(
        self,
        *,
        repo: AppointmentRepositoryPort,
        clock: ClockPort,
        opening_hours: Sequence[OpeningHoursDay],
    ) -> None:
        """Guarda los puertos con los que trabaja cada llamada.

        Args:
            repo: Repositorio de citas (en memoria hasta el Paso 6).
            clock: Reloj inyectable para ignorar huecos ya pasados.
            opening_hours: Horario de atención del comercio (falso hasta RAG/Paso 7).
        """
        self._repo = repo
        self._clock = clock
        self._hours = tuple(opening_hours)

    def get_availability(
        self, *, tenant_id: str, date: str, party_size: int | None = None
    ) -> ToolResult:
        """Huecos libres de un día: horario del comercio menos las citas existentes.

        Args:
            tenant_id: Comercio resuelto en el gateway.
            date: Día a consultar en ISO (`YYYY-MM-DD`).
            party_size: Aforo solicitado (sin efecto hasta el Paso 5).

        Returns:
            `ToolResult` con los huecos libres, ya filtrados por pasado y ocupación.

        Raises:
            ValidationError: Si falta `tenant_id` o la fecha no es ISO válida.
        """
        _require_tenant(tenant_id)
        del party_size  # TODO(decision): aforo por mesa/habitación (Paso 5)
        try:
            dia = Date.fromisoformat(date)
        except ValueError as exc:
            raise ValidationError(
                "fecha inválida en get_availability", details={"date": date}
            ) from exc

        aperturas = [h for h in self._hours if h.weekday == dia.weekday()]
        if not aperturas:
            return ToolResult(tool="get_availability", slots=[])

        ocupadas = self._repo.list_for_period(
            tenant_id=tenant_id,
            start=datetime.combine(dia, Time.min),
            end=datetime.combine(dia, Time.max),
        )
        ahora = self._clock.now()
        huecos: list[Slot] = []
        for bloque in aperturas:
            inicio = datetime.combine(dia, Time.fromisoformat(bloque.open_time))
            cierre = datetime.combine(dia, Time.fromisoformat(bloque.close_time))
            while inicio + _DURACION_HUECO <= cierre:
                fin = inicio + _DURACION_HUECO
                pasado = _es_comparable(ahora, inicio) and inicio <= ahora
                ocupado = any(inicio <= cita.starts_at < fin for cita in ocupadas)
                if not pasado and not ocupado:
                    huecos.append(Slot(start=inicio, end=fin))
                inicio = fin
        return ToolResult(tool="get_availability", slots=huecos)

    def create_appointment(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        date: str,
        time: str,
        customer_name: str,
        contact: str,
    ) -> ToolResult:
        """Crea la cita si la petición trae todos los datos mínimos (reglas 4 y 5).

        Args:
            tenant_id: Comercio resuelto en el gateway.
            correlation_id: Clave de idempotencia: repetir la petición no duplica cita.
            date: Fecha en ISO (`YYYY-MM-DD`).
            time: Hora (`HH:MM`).
            customer_name: Nombre del cliente.
            contact: Medio de contacto del cliente.

        Returns:
            `ToolResult` con la cita creada (o la ya existente de esta petición).

        Raises:
            ValidationError: Si falta `tenant_id` o fecha/hora no son ISO válidas.
            IncompleteAppointmentData: Si falta alguno de los datos mínimos.
        """
        _require_tenant(tenant_id)
        faltantes = missing_appointment_fields(
            date=date, time=time, customer_name=customer_name, contact=contact
        )
        if faltantes:
            raise IncompleteAppointmentData(
                "faltan datos para crear la cita",
                details={"faltan": ",".join(faltantes)},
            )

        existente = self._repo.find_by_correlation_id(
            tenant_id=tenant_id, correlation_id=correlation_id
        )
        if existente is not None:
            return ToolResult(tool="create_appointment", appointment=_vista(existente))

        try:
            inicio = datetime.fromisoformat(f"{date}T{time}")
        except ValueError as exc:
            raise ValidationError(
                "fecha u hora inválidas en create_appointment",
                details={"date": date, "time": time},
            ) from exc

        appointment = Appointment(
            id=f"appt-{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            starts_at=inicio,
            customer_name=customer_name,
            contact=contact,
            status="pending",
            correlation_id=correlation_id,
        )
        self._repo.save(tenant_id=tenant_id, appointment=appointment)
        return ToolResult(tool="create_appointment", appointment=_vista(appointment))

    def cancel_appointment(self, *, tenant_id: str, appointment_id: str) -> ToolResult:
        """Cancela una cita existente de este comercio (reglas 1 y 6).

        Args:
            tenant_id: Comercio resuelto en el gateway.
            appointment_id: Cita a cancelar.

        Returns:
            `ToolResult` con el identificador cancelado.

        Raises:
            ValidationError: Si falta `tenant_id`.
            TenantMismatch: Si la cita no existe en este comercio (rechazo genérico).
        """
        _require_tenant(tenant_id)
        appointment = self._repo.find(tenant_id=tenant_id, appointment_id=appointment_id)
        if appointment is None:
            raise TenantMismatch(
                "cita no encontrada en este comercio",
                details={"appointment_id": appointment_id},
            )
        cancelada = appointment.model_copy(update={"status": "cancelled"})
        self._repo.save(tenant_id=tenant_id, appointment=cancelada)
        return ToolResult(tool="cancel_appointment", cancelled_id=appointment.id)

    def get_opening_hours(self, *, tenant_id: str) -> ToolResult:
        """Horario de atención del comercio (regla 7: sale de la tool, nunca del LLM).

        Args:
            tenant_id: Comercio resuelto en el gateway.

        Returns:
            `ToolResult` con los días y franjas inyectados en la construcción.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return ToolResult(tool="get_opening_hours", hours=list(self._hours))
