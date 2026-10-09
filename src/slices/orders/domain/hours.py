"""Horario de cocina como valor de dominio (Paso 5).

Espejo de `appointments/domain/hours.py`: vive en `domain/` porque la regla de horario
de cocina (regla 6) lo necesita y el dominio no puede importar `application/`. El valor
lo inyecta la composición (`build_order_graph`); los tests lo traen a mano.

`TODO(decision)`: valores iniciales de horario por comercio (hoy fijos en la
composición; con RAG/Paso 7 saldrían del conocimiento del tenant).
"""

from pydantic import BaseModel, ConfigDict, Field


class KitchenHoursDay(BaseModel):
    """Franja de cocina de un día de la semana, en hora local naive del comercio.

    Args:
        weekday: Día de la semana (0 = lunes .. 6 = domingo).
        open_time: Hora de apertura de cocina en formato `HH:MM`.
        close_time: Hora de cierre de cocina en formato `HH:MM`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    weekday: int = Field(ge=0, le=6, description="0 = lunes .. 6 = domingo")
    open_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    close_time: str = Field(pattern=r"^\d{2}:\d{2}$")
