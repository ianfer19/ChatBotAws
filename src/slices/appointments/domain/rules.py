"""Reglas de negocio puras del turno de citas (Paso 5).

- Regla 4 (Paso 3): si faltan fecha, hora o datos del cliente, el bot pide la
  información y NO crea la cita.
- Regla 2 (Paso 5): dos citas del mismo comercio no ocupan el mismo turno (solape).
- Regla 3 (Paso 5): toda cita cae dentro del horario de atención del comercio.
"""

from collections.abc import Sequence
from datetime import datetime, time, timedelta

from .entities import Appointment
from .hours import OpeningHoursDay

CAMPOS_OBLIGATORIOS: tuple[str, ...] = ("date", "time", "customer_name", "contact")

DURACION_CITA = timedelta(hours=1)
"""Duración fija de cada cita mientras no exista configuración por comercio."""


def missing_appointment_fields(
    *,
    date: str | None,
    time: str | None,
    customer_name: str | None,
    contact: str | None,
) -> list[str]:
    """Devuelve los campos obligatorios ausentes para crear una cita.

    Args:
        date: Fecha propuesta en ISO (`YYYY-MM-DD`) o `None`.
        time: Hora propuesta (`HH:MM`) o `None`.
        customer_name: Nombre del cliente o `None`.
        contact: Medio de contacto del cliente o `None`.

    Returns:
        Los nombres de campo vacíos, en el orden de `CAMPOS_OBLIGATORIOS`; lista vacía
        si la propuesta está completa.
    """
    valores = {
        "date": date,
        "time": time,
        "customer_name": customer_name,
        "contact": contact,
    }
    return [campo for campo in CAMPOS_OBLIGATORIOS if not valores[campo]]


def overlapping_appointment(
    *, start: datetime, existing: Sequence[Appointment]
) -> Appointment | None:
    """Busca la primera cita existente que colisione con el turno propuesto.

    Dos turnos solapan si sus intervalos de `DURACION_CITA` se cruzan; las citas
    `cancelled` no ocupan turno. Usa la misma convención de zona horaria que las
    citas guardadas (`TODO(decision)`: tz compartida al conectar Aurora, Paso 6).

    Args:
        start: Inicio propuesto para la nueva cita.
        existing: Citas candidatas (en general las del día, ya filtradas por tenant).

    Returns:
        La cita que solapa o `None` si el turno está libre.
    """
    fin = start + DURACION_CITA
    for cita in existing:
        if cita.status == "cancelled":
            continue
        if (cita.starts_at.tzinfo is None) != (start.tzinfo is None):
            continue  # convenciones tz distintas no se comparan (nunca debería pasar)
        fin_cita = cita.starts_at + DURACION_CITA
        if max(start, cita.starts_at) < min(fin, fin_cita):
            return cita
    return None


def within_opening_hours(*, start: datetime, opening_hours: Sequence[OpeningHoursDay]) -> bool:
    """Indica si el turno cabe entero dentro del horario de atención del día.

    El turno completo (`start` + `DURACION_CITA`) debe caber en alguna franja del día
    de la semana; un día sin franjas (festivo, cerrado) nunca está dentro.

    Args:
        start: Inicio propuesto para la nueva cita (hora local naive).
        opening_hours: Franjas de atención inyectadas (horario del comercio).

    Returns:
        `True` si el turno cabe en el horario; `False` en caso contrario.
    """
    dia = start.date()
    hora = start.time()
    fin = (datetime.combine(dia, hora) + DURACION_CITA).time()
    for bloque in opening_hours:
        if bloque.weekday != dia.weekday():
            continue
        apertura = time.fromisoformat(bloque.open_time)
        cierre = time.fromisoformat(bloque.close_time)
        if apertura <= hora and fin <= cierre:
            return True
    return False
