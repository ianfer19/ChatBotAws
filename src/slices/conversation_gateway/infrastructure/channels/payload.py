"""Utilidades para caminar los payloads JSON de Meta (comunes a los 3 canales).

Los payloads llegan como `Mapping[str, object]` sin garantías de forma: aquí se
centraliza la navegación defensiva (sin `KeyError` sueltas), la validación de campos
obligatorios y la conversión de timestamps — WhatsApp envía segundos en string y
Messenger/Instagram milisegundos como entero.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from shared.errors import ValidationError


def objeto(valor: object) -> Mapping[str, object] | None:
    """Devuelve el valor si es un objeto JSON; `None` en caso contrario.

    Args:
        valor: Cualquier valor leído del payload.

    Returns:
        El valor como mapping, o `None` si no es un objeto.
    """
    if isinstance(valor, Mapping):
        return valor
    return None


def lista(valor: object) -> list[object]:
    """Devuelve la lista si es una lista JSON; vacía en caso contrario.

    Args:
        valor: Cualquier valor leído del payload.

    Returns:
        Los elementos de la lista o `[]`.
    """
    if isinstance(valor, list):
        return valor
    return []


def cadena(valor: object) -> str | None:
    """Devuelve el valor si es string; `None` en caso contrario.

    Args:
        valor: Cualquier valor leído del payload.

    Returns:
        El string o `None`.
    """
    if isinstance(valor, str):
        return valor
    return None


def cadena_requerida(valor: object, *, campo: str) -> str:
    """Extrae un string obligatorio (ids, wamid, mid…).

    Args:
        valor: Valor leído del payload.
        campo: Nombre del campo, solo para el mensaje de error/`details`.

    Returns:
        El string no vacío.

    Raises:
        ValidationError: Si falta o no es string (payload malformado).
    """
    resultado = cadena(valor)
    if not resultado:
        raise ValidationError(
            f"campo obligatorio ausente en el payload: {campo}",
            details={"campo": campo},
        )
    return resultado


def epoch(valor: object, *, campo: str, milisegundos: bool = False) -> datetime:
    """Convierte el timestamp del payload a `datetime` UTC.

    Args:
        valor: Timestamp del mensaje (string de segundos en WhatsApp; entero de
            milisegundos en Messenger/Instagram).
        campo: Nombre del campo, solo para el mensaje de error/`details`.
        milisegundos: `True` si el valor viene en milisegundos.

    Returns:
        El instante en UTC.

    Raises:
        ValidationError: Si no es un número entero o queda fuera de rango.
    """
    if isinstance(valor, bool) or not isinstance(valor, int | str):
        raise ValidationError(
            f"timestamp no numérico en el payload: {campo}",
            details={"campo": campo},
        )
    try:
        numero = int(valor)
    except ValueError as exc:
        raise ValidationError(
            f"timestamp no numérico en el payload: {campo}",
            details={"campo": campo},
        ) from exc
    if milisegundos:
        numero //= 1000
    try:
        return datetime.fromtimestamp(numero, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValidationError(
            f"timestamp fuera de rango en el payload: {campo}",
            details={"campo": campo},
        ) from exc
