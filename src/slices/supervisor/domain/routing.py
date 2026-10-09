"""Reglas de enrutado del supervisor: intención + confianza + `allowed_bots` → destino.

El enrutado vive en código, nunca en el prompt (regla 2 del slice): el LLM solo propone
la intención; aquí se decide a dónde va el turno y qué pasa cuando la decisión no es
segura. El saludo tiene ruta propia e incondicional (regla 1): jamás puede acabar en
ventas ni en ningún otro agente.
"""

import unicodedata
from typing import Final

from shared.contracts import AgentName, Intent

from .errors import AmbiguousIntentError, IntentNotAllowedByTenant

_UMBRAL_CONFIANZA: Final = 0.5
"""Confianza mínima de la clasificación; por debajo, ruta segura.

`TODO(verify)`: afinar el umbral con los evals del Paso 14.
"""

_RUTAS: Final[dict[Intent, AgentName]] = {
    "greeting": "supervisor",
    "smalltalk": "supervisor",
    "sales": "sales",
    "appointments": "appointments",
    "orders": "orders",
    "faq": "faq",
}
# Mapa intención → agente destino; el saludo/smalltalk siempre apunta al supervisor.

_SIEMPRE_DISPONIBLES: Final[frozenset[AgentName]] = frozenset({"supervisor", "faq"})
# El supervisor (saludo) y el FAQ (respuesta honesta) no dependen de entitlements:
# la ruta segura de la regla 4 debe existir en todo comercio.

_PALABRAS_CLAVE: Final[tuple[tuple[frozenset[str], Intent], ...]] = (
    (
        frozenset({"cita", "citas", "reservar", "reserva", "agendar", "agendado", "turno"}),
        "appointments",
    ),
    (frozenset({"pedido", "pedidos", "pedir", "orden"}), "orders"),
    (frozenset({"precio", "precios", "comprar", "venta", "producto", "costo"}), "sales"),
)
# Palabras de emergencia cuando Bedrock no responde (fila «Fallo de LLMPort» de AGENTS).


def resolve_route(
    *, intent: Intent, confidence: float, allowed_bots: frozenset[AgentName]
) -> AgentName:
    """Decide el agente destino de un turno a partir de la intención clasificada.

    Args:
        intent: Intención propuesta por el clasificador (contrato `Intent`).
        confidence: Confianza reportada por el clasificador (0 a 1).
        allowed_bots: Entitlements del comercio: bots que tiene activados.

    Returns:
        El agente destino (`AgentName`); el saludo/smalltalk siempre `supervisor`.

    Raises:
        AmbiguousIntentError: Si `confidence` queda por debajo del umbral (ruta segura).
        IntentNotAllowedByTenant: Si el destino no está en `allowed_bots` y no es una
            de las rutas siempre disponibles (`supervisor`, `faq`).

    Example:
        >>> resolve_route(intent="greeting", confidence=0.9, allowed_bots=frozenset())
        'supervisor'
    """
    if confidence < _UMBRAL_CONFIANZA:
        raise AmbiguousIntentError(
            "intención ambigua por confianza baja",
            details={"intent": intent, "confidence": str(confidence)},
        )
    destino = _RUTAS[intent]
    if destino in _SIEMPRE_DISPONIBLES:
        return destino
    if destino not in allowed_bots:
        raise IntentNotAllowedByTenant(
            "el comercio no tiene habilitado ese agente",
            details={"intent": intent, "destino": destino},
        )
    return destino


def intent_from_keywords(text: str) -> Intent:
    """Clasificación de emergencia cuando el LLM no está disponible (nunca inventa).

    Palabras clave deterministas sobre el texto normalizado; lo que no reconoce cae en
    `faq`, la ruta honesta por defecto (regla 4).

    Args:
        text: Texto crudo del mensaje del cliente.

    Returns:
        La intención más probable según las palabras clave, o `faq` si no hay match.

    Example:
        >>> intent_from_keywords("Quiero una CITA el viernes")
        'appointments'
    """
    tokens = set(_normalizar(text).split())
    for palabras, intent in _PALABRAS_CLAVE:
        if tokens & palabras:
            return intent
    return "faq"


def _normalizar(text: str) -> str:
    """Minúsculas, sin acentos y sin puntuación: una sola forma para comparar tokens.

    Args:
        text: Texto crudo.

    Returns:
        Texto normalizado con palabras separadas por espacios.
    """
    minusculas = unicodedata.normalize("NFD", text.lower())
    sin_acentos = "".join(c for c in minusculas if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() else " " for c in sin_acentos)


def saludo(branding: str | None) -> str:
    """Saludo neutral propio del supervisor (regla 1: ruta propia, jamás a ventas).

    Args:
        branding: Nombre comercial del comercio; hasta el Paso 9 es el `tenant_id`.

    Returns:
        El saludo ya redactado; sin branding, la versión genérica.

    Example:
        >>> saludo("Sede_Elite_01")
        'Buenas, bienvenido a Sede_Elite_01, ¿en qué te ayudo?'
        >>> saludo(None)
        'Buenas, ¿en qué te ayudo?'
    """
    if not branding:
        return "Buenas, ¿en qué te ayudo?"
    return f"Buenas, bienvenido a {branding}, ¿en qué te ayudo?"
