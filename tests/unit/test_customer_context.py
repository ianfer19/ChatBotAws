"""Tests del slice customer_context (Paso 4): CRUD, TTL, aislamiento y la tool de lectura."""

from datetime import datetime, timedelta

import pytest

from shared.contracts import CustomerContext
from shared.errors import ValidationError
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.domain.errors import ContextStaleError
from slices.customer_context.domain.ports import CustomerContextPort
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Otro_Comercio_01"
CLIENTE = "57300111111"
INICIO = datetime(2026, 3, 2, 8, 0)
TTL = timedelta(days=30)


class _Reloj:
    """Reloj inyectable con hora controlable: los tests lo avanzan para vencer el TTL."""

    def __init__(self, ahora: datetime) -> None:
        """Guarda el instante inicial que devolverá `now`.

        Args:
            ahora: Hora inicial del test.
        """
        self.ahora = ahora

    def now(self) -> datetime:
        """Devuelve la hora actual del reloj del test.

        Returns:
            El instante configurado (los tests lo mutan para simular el paso del tiempo).
        """
        return self.ahora


def _contexto(
    *,
    name: str | None = None,
    preferences: dict[str, str] | None = None,
    tags: list[str] | None = None,
) -> CustomerContext:
    """Construye un contexto del tenant de prueba con los campos que pida el test.

    Args:
        name: Nombre del cliente (si el test lo necesita).
        preferences: Preferencias a guardar (por defecto, ninguna).
        tags: Etiquetas a guardar (por defecto, ninguna).

    Returns:
        Contexto inmutable listo para guardar.
    """
    return CustomerContext(
        tenant_id=TENANT,
        customer_id=CLIENTE,
        name=name,
        preferences=preferences if preferences is not None else {},
        tags=tags if tags is not None else [],
    )


def _store() -> tuple[InMemoryCustomerContextStore, _Reloj]:
    """Crea el almacén en memoria con su reloj controlable.

    Returns:
        Tupla (almacén, reloj) para avanzar el tiempo en cada test.
    """
    reloj = _Reloj(INICIO)
    return InMemoryCustomerContextStore(clock=reloj, ttl=TTL), reloj


def _tools() -> tuple[CustomerContextTools, InMemoryCustomerContextStore, _Reloj]:
    """Crea las tools sobre el almacén en memoria, compartiendo su reloj.

    Returns:
        Tupla (tools, almacén, reloj).
    """
    almacen, reloj = _store()
    return CustomerContextTools(store=almacen, clock=reloj), almacen, reloj


def test_doble_cumple_el_puerto_del_dominio() -> None:
    """El almacén en memoria implementa el `CustomerContextPort` (mismo patrón que citas)."""
    almacen, _ = _store()
    assert isinstance(almacen, CustomerContextPort)


def test_guardar_y_recuperar_contexto() -> None:
    """Lo que se guarda se devuelve idéntico dentro del mismo comercio."""
    almacen, _ = _store()
    contexto = _contexto(name="Ana", preferences={"idioma": "es"}, tags=["vip"])
    almacen.save(tenant_id=TENANT, context=contexto)
    assert almacen.get(tenant_id=TENANT, customer_id=CLIENTE) == contexto


def test_cliente_nuevo_tiene_contexto_vacio() -> None:
    """Un cliente sin historial no es error: la tool devuelve el contexto por defecto."""
    tools, almacen, _ = _tools()
    assert almacen.get(tenant_id=TENANT, customer_id=CLIENTE) is None
    contexto = tools.get_customer_context(tenant_id=TENANT, customer_id=CLIENTE)
    assert contexto.tenant_id == TENANT
    assert contexto.customer_id == CLIENTE
    assert contexto.name is None
    assert contexto.preferences == {}
    assert contexto.tags == []
    assert contexto.last_seen_at is None


def test_un_contexto_de_otro_comercio_es_inexistente() -> None:
    """El aislamiento está en la clave: otro comercio ni siquiera lo encuentra."""
    almacen, _ = _store()
    almacen.save(tenant_id=TENANT, context=_contexto(name="Ana"))
    assert almacen.get(tenant_id=OTRO_TENANT, customer_id=CLIENTE) is None
    tools = CustomerContextTools(store=almacen, clock=_Reloj(INICIO))
    ajeno = tools.get_customer_context(tenant_id=OTRO_TENANT, customer_id=CLIENTE)
    assert ajeno.name is None


def test_no_se_puede_guardar_contexto_ajeno_al_tenant() -> None:
    """`save` valida la coincidencia aunque el `tenant_id` venga por fuera (defensa)."""
    almacen, _ = _store()
    with pytest.raises(ValidationError):
        almacen.save(tenant_id=OTRO_TENANT, context=_contexto())


@pytest.mark.parametrize(
    "tenant_id, customer_id",
    [("", CLIENTE), (TENANT, "")],
)
def test_sin_identificadores_no_se_trabaja(tenant_id: str, customer_id: str) -> None:
    """Ni el almacén ni la tool operan «a ciegas»: ids vacíos son error de validación."""
    almacen, _ = _store()
    with pytest.raises(ValidationError):
        almacen.get(tenant_id=tenant_id, customer_id=customer_id)
    tools = CustomerContextTools(store=almacen, clock=_Reloj(INICIO))
    with pytest.raises(ValidationError):
        tools.get_customer_context(tenant_id=tenant_id, customer_id=customer_id)
    with pytest.raises(ValidationError):
        tools.update_customer_context(tenant_id=tenant_id, customer_id=customer_id)


def test_contexto_caducado_lanza_error_de_dominio() -> None:
    """Tras el TTL el almacén señala la caducidad con el error tipado del dominio."""
    almacen, reloj = _store()
    almacen.save(tenant_id=TENANT, context=_contexto())
    reloj.ahora = INICIO + TTL + timedelta(seconds=1)
    with pytest.raises(ContextStaleError):
        almacen.get(tenant_id=TENANT, customer_id=CLIENTE)


def test_tool_traduce_el_ttl_vencido_a_contexto_vacio(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La caducidad no interrumpe el turno: tool → vacío + log de relectura (regla de errores)."""
    tools, almacen, reloj = _tools()
    almacen.save(tenant_id=TENANT, context=_contexto(name="Ana"))
    reloj.ahora = INICIO + TTL + timedelta(seconds=1)
    with caplog.at_level("INFO"):
        contexto = tools.get_customer_context(tenant_id=TENANT, customer_id=CLIENTE)
    assert contexto.name is None
    assert any("customer_context.stale" in record.getMessage() for record in caplog.records)


def test_update_fusiona_y_sella_la_ultima_visita() -> None:
    """La escritura por eventos fusiona (preferencias nuevas ganan, tags se acumulan)."""
    tools, almacen, reloj = _tools()
    tools.update_customer_context(
        tenant_id=TENANT,
        customer_id=CLIENTE,
        name="Ana",
        preferences={"idioma": "es"},
        tags=["vip"],
    )
    reloj.ahora = INICIO + timedelta(minutes=5)
    actualizado = tools.update_customer_context(
        tenant_id=TENANT,
        customer_id=CLIENTE,
        preferences={"idioma": "en", "tono": "formal"},
        tags=["vip", "nuevo"],
    )
    assert actualizado.name == "Ana"
    assert actualizado.preferences == {"idioma": "en", "tono": "formal"}
    assert actualizado.tags == ["vip", "nuevo"]
    assert actualizado.last_seen_at == reloj.ahora
    assert almacen.get(tenant_id=TENANT, customer_id=CLIENTE) == actualizado


def test_update_con_contexto_caducado_empieza_de_cero() -> None:
    """Si el contexto venció, la escritura no falla: reconstruye desde lo nuevo y renueva el TTL."""
    tools, almacen, reloj = _tools()
    tools.update_customer_context(tenant_id=TENANT, customer_id=CLIENTE, name="Ana")
    reloj.ahora = INICIO + TTL + timedelta(days=1)
    reconstruido = tools.update_customer_context(
        tenant_id=TENANT, customer_id=CLIENTE, tags=["nuevo"]
    )
    assert reconstruido.name is None
    assert reconstruido.tags == ["nuevo"]
    assert almacen.get(tenant_id=TENANT, customer_id=CLIENTE) == reconstruido
