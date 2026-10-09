"""Reglas del dominio del supervisor: enrutado, palabras clave y saludo (Paso 4)."""

import pytest

from shared.contracts import AgentName, Intent
from slices.supervisor.domain.errors import AmbiguousIntentError, IntentNotAllowedByTenant
from slices.supervisor.domain.routing import intent_from_keywords, resolve_route, saludo

_BOTS: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
"""Entitlements completos del comercio de prueba."""

RUTAS: list[tuple[Intent, AgentName]] = [
    ("greeting", "supervisor"),
    ("smalltalk", "supervisor"),
    ("sales", "sales"),
    ("appointments", "appointments"),
    ("orders", "orders"),
    ("faq", "faq"),
]

PALABRAS: list[tuple[str, Intent]] = [
    ("Quiero una CITA el viernes", "appointments"),
    ("puedes agendar mi turno", "appointments"),
    ("hazme un PEDIDO de pizza", "orders"),
    ("¿cuánto cuesta este PRODUCTO?", "sales"),
    ("hola qué tal todo", "faq"),
    ("", "faq"),
]


@pytest.mark.parametrize("intent,destino_esperado", RUTAS)
def test_tabla_de_intencion_a_destino(intent: Intent, destino_esperado: AgentName) -> None:
    """Cada intención del contrato tiene un único destino con entitlements completos."""
    assert resolve_route(intent=intent, confidence=0.9, allowed_bots=_BOTS) == destino_esperado


def test_el_saludo_nunca_enruta_a_ventas() -> None:
    """Regresión 7.2: `greeting`/`smalltalk` → `supervisor` con cualquier `allowed_bots`.

    El destino del saludo es `supervisor` por construcción, así que jamás puede acabar
    en `sales`; el test lo fija además con comercios sin ningún bot habilitado.
    """
    intenciones: tuple[Intent, ...] = ("greeting", "smalltalk")
    for intent in intenciones:
        destino = resolve_route(intent=intent, confidence=0.99, allowed_bots=frozenset())
        assert destino == "supervisor"


def test_allowed_bots_restringe_la_ruta() -> None:
    """Comercio sin citas: `appointments` se rechaza y `sales` sigue pasando."""
    with pytest.raises(IntentNotAllowedByTenant):
        resolve_route(intent="appointments", confidence=0.9, allowed_bots=frozenset({"sales"}))
    assert (
        resolve_route(intent="sales", confidence=0.9, allowed_bots=frozenset({"sales"})) == "sales"
    )


def test_faq_y_supervisor_no_dependen_de_allowed_bots() -> None:
    """La ruta segura (`faq`) y el saludo existen en todo comercio (regla 4)."""
    assert resolve_route(intent="faq", confidence=0.9, allowed_bots=frozenset()) == "faq"
    assert (
        resolve_route(intent="greeting", confidence=0.9, allowed_bots=frozenset()) == "supervisor"
    )


def test_confianza_baja_es_ambigua() -> None:
    """Por debajo del umbral no se enruta: error de dominio para la ruta segura."""
    with pytest.raises(AmbiguousIntentError):
        resolve_route(intent="sales", confidence=0.49, allowed_bots=frozenset({"sales"}))


@pytest.mark.parametrize("texto,intencion_esperada", PALABRAS)
def test_clasificacion_de_emergencia_por_palabras(texto: str, intencion_esperada: Intent) -> None:
    """Cuando Bedrock cae, las palabras clave deciden y lo demás cae en `faq`."""
    assert intent_from_keywords(texto) == intencion_esperada


def test_las_palabras_clave_ignoran_mayusculas_y_acentos() -> None:
    """La normalización hace el fallback determinista con cualquier forma de escribir."""
    assert intent_from_keywords("CITA, por favor") == "appointments"
    assert intent_from_keywords("reserva") == "appointments"


def test_saludo_con_branding_del_comercio() -> None:
    """El saludo usa el branding del comercio y es neutral (no promociona bots)."""
    assert saludo("Sede_Elite_01") == "Buenas, bienvenido a Sede_Elite_01, ¿en qué te ayudo?"
    assert "cita" not in saludo("Sede_Elite_01")
    assert "venta" not in saludo("Sede_Elite_01")


def test_saludo_sin_branding_es_generico() -> None:
    """Sin nombre comercial el saludo sigue siendo cordial y completo."""
    assert saludo(None) == "Buenas, ¿en qué te ayudo?"
    assert saludo("") == "Buenas, ¿en qué te ayudo?"
