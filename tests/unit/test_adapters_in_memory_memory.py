"""Doble en memoria del port de conversaciones (Paso 8): aislamiento y contrato.

Prueban `InMemoryMemoryStore` de `adapters/in_memory`, el mismo doble que usa el
`PortCheckpointSaver` en los tests, en los evals y en el REPL.
"""

import pytest

from adapters.in_memory import InMemoryMemoryStore
from shared.errors import ValidationError
from shared.ports import MemoryStorePort


def test_es_un_memory_store_port() -> None:
    """El doble satisface el Protocol que exige el checkpointer."""
    assert isinstance(InMemoryMemoryStore(), MemoryStorePort)


def test_put_y_get_round_trip() -> None:
    """Lo que se guarda se devuelve tal cual."""
    store = InMemoryMemoryStore()
    store.put(tenant_id="t1", conversation_id="c1", payload='{"v": 1}')
    assert store.get(tenant_id="t1", conversation_id="c1") == '{"v": 1}'


def test_put_sobrescribe_el_payload_anterior() -> None:
    """Una escritura posterior reemplaza a la anterior (no duplica claves)."""
    store = InMemoryMemoryStore()
    store.put(tenant_id="t1", conversation_id="c1", payload="uno")
    store.put(tenant_id="t1", conversation_id="c1", payload="dos")
    assert store.get(tenant_id="t1", conversation_id="c1") == "dos"


def test_get_de_una_conversacion_inexistente_devuelve_none() -> None:
    """Leer algo nunca escrito no falla: devuelve `None`."""
    store = InMemoryMemoryStore()
    assert store.get(tenant_id="t1", conversation_id="nunca") is None


def test_el_mismo_conversation_id_de_dos_tenants_no_se_mezcla() -> None:
    """La clave compuesta aísla comercios con la misma conversación."""
    store = InMemoryMemoryStore()
    store.put(tenant_id="t1", conversation_id="c1", payload="de t1")
    store.put(tenant_id="t2", conversation_id="c1", payload="de t2")
    assert store.get(tenant_id="t1", conversation_id="c1") == "de t1"
    assert store.get(tenant_id="t2", conversation_id="c1") == "de t2"


def test_delete_borra_solo_la_conversacion_pedida() -> None:
    """El borrado es exacto por clave; lo demás sigue intacto."""
    store = InMemoryMemoryStore()
    store.put(tenant_id="t1", conversation_id="c1", payload="a")
    store.put(tenant_id="t1", conversation_id="c2", payload="b")
    store.delete(tenant_id="t1", conversation_id="c1")
    assert store.get(tenant_id="t1", conversation_id="c1") is None
    assert store.get(tenant_id="t1", conversation_id="c2") == "b"


def test_delete_de_una_conversacion_inexistente_no_falla() -> None:
    """Borrar algo que no existe es un no-op (idempotente)."""
    store = InMemoryMemoryStore()
    store.delete(tenant_id="t1", conversation_id="nunca")


@pytest.mark.parametrize(
    ("tenant_id", "conversation_id"),
    [("", "c1"), ("t1", "")],
)
def test_put_sin_tenant_o_conversation_lanza_validation_error(
    *, tenant_id: str, conversation_id: str
) -> None:
    """La escritura sin clave completa es un error tipado de validación."""
    store = InMemoryMemoryStore()
    with pytest.raises(ValidationError):
        store.put(tenant_id=tenant_id, conversation_id=conversation_id, payload="x")
