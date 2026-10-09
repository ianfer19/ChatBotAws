"""Política de riesgo de las citas: decide `AUTO` o `CONFIRM` sin LLM (ADR 0011.3).

La política es código determinista testeable; los umbrales y señales iniciales son
deliberadamente conservadores y se ajustan con métricas reales
(`TODO(decision)`: señales adicionales — penalidad por cancelación, urgencia del
mismo día, cliente recurrente — al llegar tráfico en el Paso 13).
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence

from shared.contracts.pending import ConfirmationPolicy, PolicyDecision

_INDICADORES_FECHA = re.compile(
    r"\b(hoy|ma[nñ]ana|pasado ma[nñ]ana|lunes|martes|mi[eé]rcoles|jueves|viernes|"
    r"s[aá]bado|domingo|\d{1,2}\s+de\s+[a-z]+|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b",
    re.IGNORECASE,
)
"""Expresiones con las que un cliente da una fecha sin escribirla en ISO."""

_INDICADORES_HORA = re.compile(
    r"\b\d{1,2}:\d{2}\b|\ba\s+las\s+\d{1,2}\b|\b\d{1,2}\s*(?:h|horas)\b",
    re.IGNORECASE,
)
"""Expresiones con las que un cliente da una hora («10:00», «a las 10», «10 horas»)."""


def _normalizar(texto: str) -> str:
    """Normaliza un texto para compararlo: minúsculas y sin acentos.

    Args:
        texto: Cadena de entrada (mensaje del cliente o valor de un campo).

    Returns:
        La cadena en minúsculas sin marcas diacríticas.
    """
    base = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(caracter for caracter in base if not unicodedata.combining(caracter))


def detect_inferred_fields(*, message: str, fields: Mapping[str, str]) -> tuple[str, ...]:
    """Detecta los campos que el LLM infirió en lugar de decirlos el cliente.

    Un campo se da por dicho si su valor literal aparece en el mensaje (p. ej.
    `2026-03-05`, `Ana Pérez`, `3001112233`) o si el mensaje trae una expresión
    equivalente para fecha u hora («el viernes», «a las 10»). Es una heurística
    deliberadamente conservadora: ante la duda el campo cuenta como inferido y la
    política exige confirmación (`TODO(verify)`: calibrar con métricas reales, Paso 13).

    Args:
        message: Texto crudo del mensaje del cliente.
        fields: Campos de la propuesta con sus valores (todos no vacíos).

    Returns:
        Nombres de campo inferidos, en el orden de `fields`; vacío si todo se dijo.
    """
    mensaje = _normalizar(message)
    inferidos: list[str] = []
    for nombre, valor in fields.items():
        if not valor:
            continue
        if _normalizar(valor) in mensaje:
            continue
        if nombre == "date" and _INDICADORES_FECHA.search(mensaje):
            continue
        if nombre == "time" and _INDICADORES_HORA.search(mensaje):
            continue
        inferidos.append(nombre)
    return tuple(inferidos)


def decide_appointment(*, inferred_fields: Sequence[str]) -> PolicyDecision:
    """Aplica la política de riesgo de citas a una propuesta recién armada.

    Regla v1: si algún campo obligatorio fue inferido por el modelo, la propuesta
    exige confirmación explícita (`CONFIRM`); si todo lo dijo el cliente, se ejecuta
    solo con ventana de deshacer (`AUTO`).

    Args:
        inferred_fields: Campos inferidos devueltos por `detect_inferred_fields`.

    Returns:
        `PolicyDecision` con `AUTO` (sin motivos) o `CONFIRM` (un motivo por campo
        inferido, para logs y tests).
    """
    if inferred_fields:
        motivos = tuple(f"campo_inferido:{campo}" for campo in inferred_fields)
        return PolicyDecision(policy=ConfirmationPolicy.CONFIRM, reasons=motivos)
    return PolicyDecision(policy=ConfirmationPolicy.AUTO)
