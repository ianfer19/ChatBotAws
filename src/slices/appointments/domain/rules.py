"""Reglas de negocio puras del turno de citas (Paso 3: datos mínimos).

Regla 4 del slice: si faltan fecha, hora o datos del cliente, el bot pide la
información y NO crea la cita. Solapes y horario de atención (reglas 2 y 3) llegan con
el Paso 5; aquí solo se decide si hay datos suficientes para continuar.
"""

CAMPOS_OBLIGATORIOS: tuple[str, ...] = ("date", "time", "customer_name", "contact")


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
