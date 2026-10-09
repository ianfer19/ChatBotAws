"""Horario de atención como valor de dominio (Paso 5).

Vive en `domain/` porque las reglas de horario (regla 3) lo necesitan y el dominio no
puede importar `application/`. El módulo `application/schemas.py` lo re-exporta para
que las tools, el grafo y los tests mantengan su import actual.
"""

from pydantic import BaseModel, ConfigDict, Field


class OpeningHoursDay(BaseModel):
    """Horario de atención de un día de la semana, en hora local naive del comercio.

    Args:
        weekday: Día de la semana (0 = lunes .. 6 = domingo).
        open_time: Hora de apertura en formato `HH:MM`.
        close_time: Hora de cierre en formato `HH:MM`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    weekday: int = Field(ge=0, le=6, description="0 = lunes .. 6 = domingo")
    open_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    close_time: str = Field(pattern=r"^\d{2}:\d{2}$")
