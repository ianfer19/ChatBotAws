"""Tests del kernel: los ports son Protocol y los dobles los satisfacen (shared/ports)."""

from collections.abc import Mapping
from datetime import UTC, datetime

from shared.ports import ClockPort, EventBusPort, LLMPort


class _FakeClock:
    """Reloj controlado: siempre devuelve el instante fijado."""

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class _FakeLLM:
    """Modelo fijo para tests: sin red ni tokens."""

    def complete(self, *, system: str, prompt: str, max_tokens: int | None = None) -> str:
        return f"respuesta a: {prompt}"


class _FakeBus:
    """Captura los eventos publicados en lugar de encolarlos."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def publish(self, event_name: str, payload: Mapping[str, object]) -> None:
        self.events.append((event_name, dict(payload)))


class _NotAPort:
    """Clase que no implementa ningún port (caso negativo)."""

    def unrelated(self) -> None:
        return None


def test_dobles_satisfacen_sus_ports() -> None:
    """La DI manual funciona: cualquier doble con la firma correcta pasa el isinstance."""
    instant = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    assert isinstance(_FakeClock(instant), ClockPort)
    assert isinstance(_FakeLLM(), LLMPort)
    assert isinstance(_FakeBus(), EventBusPort)


def test_clase_sin_la_firma_no_satisface_el_port() -> None:
    """`isinstance` del protocolo distingue dobles incompletos."""
    assert not isinstance(_NotAPort(), ClockPort)
    assert not isinstance(_NotAPort(), LLMPort)
    assert not isinstance(_NotAPort(), EventBusPort)


def test_reloj_falso_devuelve_el_instante_fijado() -> None:
    """El dominio verá siempre el mismo reloj en el test (sin dormir ni monkeypatch)."""
    instant = datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
    assert _FakeClock(instant).now() == instant


def test_llm_falso_devuelve_texto() -> None:
    """El adapter falso cumple la firma `complete(system=..., prompt=...) -> str`."""
    respuesta = _FakeLLM().complete(system="eres útil", prompt="hola")
    assert respuesta == "respuesta a: hola"


def test_bus_falso_guarda_evento_y_payload() -> None:
    """El doble del bus retiene el nombre y una copia inmutable-en-el-hecho del payload."""
    bus = _FakeBus()
    bus.publish("inbound.message", {"tenant_id": "Sede_Elite_01"})
    assert bus.events == [("inbound.message", {"tenant_id": "Sede_Elite_01"})]
