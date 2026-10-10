"""`PortCheckpointSaver`: checkpointer de LangGraph tras un port (Paso 8).

Prueban el adaptador completo contra un doble en memoria: round-trip del checkpoint,
writes pendientes, aislamiento por hilo y por tenant, envelope JSON y límites
deliberados (solo el checkpoint más reciente, formato del `thread_id`).
"""

import asyncio
import json
from typing import Any

import pytest
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    RunnableConfig,
    empty_checkpoint,
)

from adapters.checkpointer import PortCheckpointSaver, thread_id_de
from adapters.in_memory import InMemoryMemoryStore
from shared.errors import ValidationError
from shared.ports import MemoryStorePort

_TENANT = "Sede_Elite_01"
_OTRO_TENANT = "Sede_Otro_02"
_CONVERSACION = "conv-1"


class _PortConTtl(InMemoryMemoryStore):
    """Doble que además recuerda el último `ttl_seconds` que le pasó el saver."""

    def __init__(self) -> None:
        super().__init__()
        self.ttl_ultimo: int | None = None

    def put(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        payload: str,
        ttl_seconds: int | None = None,
    ) -> None:
        self.ttl_ultimo = ttl_seconds
        super().put(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            payload=payload,
            ttl_seconds=ttl_seconds,
        )


def _thread(*, tenant: str = _TENANT, conversacion: str = _CONVERSACION) -> str:
    """Hilo de prueba con el formato canónico."""
    return thread_id_de(tenant_id=tenant, conversation_id=conversacion)


def _config(thread_id: str, checkpoint_id: str | None = None) -> RunnableConfig:
    """Configuración mínima de LangGraph para el saver."""
    configurables: dict[str, Any] = {"thread_id": thread_id, "checkpoint_ns": ""}
    if checkpoint_id is not None:
        configurables["checkpoint_id"] = checkpoint_id
    return {"configurable": configurables}


def _checkpoint(**channel_values: Any) -> Checkpoint:
    """Checkpoint vacío con los canales indicados (tipos no JSON incluidos)."""
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = channel_values
    return checkpoint


def _metadata(step: int = 0) -> CheckpointMetadata:
    """Metadata de paso válida para `put`."""
    return {"source": "loop", "step": step, "parents": {}}


def _saver(store: MemoryStorePort | None = None, ttl: int | None = None) -> PortCheckpointSaver:
    """Saver de prueba sobre el port indicado (o el doble en memoria)."""
    return PortCheckpointSaver(
        store=store if store is not None else InMemoryMemoryStore(), ttl_seconds=ttl
    )


def test_es_un_base_checkpoint_saver() -> None:
    """LangGraph solo acepta un `BaseCheckpointSaver`; el adaptador lo cumple."""
    assert isinstance(_saver(), BaseCheckpointSaver)
    assert isinstance(_saver(), PortCheckpointSaver)


def test_es_un_memory_store_port_el_doble() -> None:
    """El doble que usa el saver satisface el Protocol del port."""
    assert isinstance(InMemoryMemoryStore(), MemoryStorePort)


def test_get_tuple_sin_escrituras_devuelve_none() -> None:
    """Un hilo desconocido no falla: no hay checkpoint que devolver."""
    assert _saver().get_tuple(_config(_thread())) is None


def test_put_y_get_devuelven_el_checkpoint_mas_reciente_con_su_padre() -> None:
    """El segundo `put` reemplaza al primero y conserva la referencia de padre."""
    saver = _saver()
    primero = saver.put(_config(_thread()), _checkpoint(reply="hola"), _metadata(0), {})
    segundo = saver.put(
        _config(_thread(), str(primero["configurable"]["checkpoint_id"])),
        _checkpoint(reply="adios"),
        _metadata(1),
        {},
    )
    tupla = saver.get_tuple(_config(_thread()))
    assert tupla is not None
    assert tupla.checkpoint["id"] == segundo["configurable"]["checkpoint_id"]
    assert tupla.checkpoint["channel_values"] == {"reply": "adios"}
    assert tupla.parent_config is not None
    assert (
        tupla.parent_config["configurable"]["checkpoint_id"]
        == (primero["configurable"]["checkpoint_id"])
    )
    assert tupla.metadata["step"] == 1


def test_get_tuple_con_checkpoint_id_distinto_del_ultimo_devuelve_none() -> None:
    """Límite documentado: solo vive el checkpoint más reciente (sin time-travel)."""
    saver = _saver()
    primero = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    saver.put(
        _config(_thread(), str(primero["configurable"]["checkpoint_id"])),
        _checkpoint(),
        _metadata(1),
        {},
    )
    assert (
        saver.get_tuple(_config(_thread(), str(primero["configurable"]["checkpoint_id"]))) is None
    )


def test_get_tuple_con_el_id_del_ultimo_si_lo_devuelve() -> None:
    """Pedir explícitamente el checkpoint vigente funciona igual que el más reciente."""
    saver = _saver()
    guardado = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    checkpoint_id = str(guardado["configurable"]["checkpoint_id"])
    tupla = saver.get_tuple(_config(_thread(), checkpoint_id))
    assert tupla is not None
    assert tupla.checkpoint["id"] == checkpoint_id


def test_put_writes_quedan_como_pending_writes_del_checkpoint() -> None:
    """Los writes de una tarea quedan pendientes en la tupla del checkpoint."""
    saver = _saver()
    guardado = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    saver.put_writes(
        guardado,
        [("llm", {"texto": "hola"})],
        "task-1",
    )
    tupla = saver.get_tuple(_config(_thread()))
    assert tupla is not None
    assert tupla.pending_writes == [("task-1", "llm", {"texto": "hola"})]


def test_put_writes_repetido_no_se_duplica() -> None:
    """La misma escritura de la misma tarea se registra una sola vez."""
    saver = _saver()
    guardado = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    saver.put_writes(guardado, [("llm", "valor")], "task-1")
    saver.put_writes(guardado, [("llm", "valor")], "task-1")
    tupla = saver.get_tuple(_config(_thread()))
    assert tupla is not None
    assert len(tupla.pending_writes or []) == 1


def test_writes_de_canales_especiales_admiten_repeticion() -> None:
    """Los canales con índice negativo (`__error__`) no se deduplican (paridad con
    `InMemorySaver` de LangGraph)."""
    saver = _saver()
    guardado = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    saver.put_writes(guardado, [("__error__", "fallo")], "task-1")
    saver.put_writes(guardado, [("__error__", "fallo")], "task-1")
    tupla = saver.get_tuple(_config(_thread()))
    assert tupla is not None
    assert len(tupla.pending_writes or []) == 2


def test_put_avanzado_limpia_los_writes_del_checkpoint_anterior() -> None:
    """Al avanzar el estado vigente, los writes ya consumidos desaparecen."""
    saver = _saver()
    primero = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    saver.put_writes(primero, [("llm", "valor")], "task-1")
    saver.put(
        _config(_thread(), str(primero["configurable"]["checkpoint_id"])),
        _checkpoint(),
        _metadata(1),
        {},
    )
    tupla = saver.get_tuple(_config(_thread()))
    assert tupla is not None
    assert tupla.pending_writes == []


def test_write_de_un_checkpoint_desactualizado_se_descarta() -> None:
    """Un write que llega tarde (checkpoint ya avanzado) no contamina el estado."""
    saver = _saver()
    primero = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    saver.put(
        _config(_thread(), str(primero["configurable"]["checkpoint_id"])),
        _checkpoint(),
        _metadata(1),
        {},
    )
    saver.put_writes(primero, [("llm", "tarde")], "task-1")
    tupla = saver.get_tuple(_config(_thread()))
    assert tupla is not None
    assert tupla.pending_writes == []


def test_write_sin_checkpoint_previo_se_descarta() -> None:
    """Sin estado vigente no hay a dónde adjuntar el write: se ignora con log."""
    saver = _saver()
    saver.put_writes(_config(_thread()), [("llm", "valor")], "task-1")
    assert saver.get_tuple(_config(_thread())) is None


def test_hilos_distintos_no_comparten_estado() -> None:
    """Conversaciones distintas (y comercios distintos) viven en claves separadas."""
    saver = _saver()
    saver.put(_config(_thread(conversacion="conv-a")), _checkpoint(reply="a"), _metadata(0), {})
    saver.put(
        _config(_thread(conversacion="conv-b")),
        _checkpoint(reply="b"),
        _metadata(0),
        {},
    )
    saver.put(
        _config(_thread(tenant=_OTRO_TENANT)),
        _checkpoint(reply="otro"),
        _metadata(0),
        {},
    )
    replies = []
    for thread in (
        _thread(conversacion="conv-a"),
        _thread(conversacion="conv-b"),
        _thread(tenant=_OTRO_TENANT),
    ):
        tupla = saver.get_tuple(_config(thread))
        assert tupla is not None
        replies.append(tupla.checkpoint["channel_values"]["reply"])
    assert replies == ["a", "b", "otro"]


def test_delete_thread_borra_solo_su_conversacion() -> None:
    """El borrado exige el formato del hilo y no toca a los demás."""
    saver = _saver()
    borrable = _thread(conversacion="borrar")
    conservada = _thread(conversacion="conservar")
    saver.put(_config(borrable), _checkpoint(), _metadata(0), {})
    saver.put(_config(conservada), _checkpoint(), _metadata(0), {})
    saver.delete_thread(borrable)
    assert saver.get_tuple(_config(borrable)) is None
    assert saver.get_tuple(_config(conservada)) is not None


def test_thread_de_un_solo_tenant_embebido_es_valido() -> None:
    """`thread_id_de` exige ambos campos y prohíbe el separador en ellos."""
    assert thread_id_de(tenant_id="t1", conversation_id="c1") == "t1#c1"
    with pytest.raises(ValidationError):
        thread_id_de(tenant_id="", conversation_id="c1")
    with pytest.raises(ValidationError):
        thread_id_de(tenant_id="t1", conversation_id="")
    with pytest.raises(ValidationError):
        thread_id_de(tenant_id="t#1", conversation_id="c1")
    with pytest.raises(ValidationError):
        thread_id_de(tenant_id="t1", conversation_id="c#1")


@pytest.mark.parametrize(
    "thread_id",
    ["", "conv-sin-tenant", "#conv", "tenant#", "#"],
)
def test_hilo_con_formato_invalido_lanza_validation_error(*, thread_id: str) -> None:
    """Un `thread_id` sin tenant no puede partirse: fallo de validación tipado."""
    saver = _saver()
    with pytest.raises(ValidationError):
        saver.get_tuple(_config(thread_id))
    with pytest.raises(ValidationError):
        saver.put(_config(thread_id), _checkpoint(), _metadata(0), {})
    with pytest.raises(ValidationError):
        saver.delete_thread(thread_id)


def test_payload_es_json_de_texto_inspeccionable() -> None:
    """El port guarda `str`; el envelope es JSON puro (sin bytes crudos)."""
    store = InMemoryMemoryStore()
    saver = _saver(store)
    saver.put(_config(_thread()), _checkpoint(dato=b"\x00\x01"), _metadata(0), {})
    payload = store.get(tenant_id=_TENANT, conversation_id=_CONVERSACION)
    assert payload is not None
    envelope = json.loads(payload)
    assert envelope["v"] == 1
    assert isinstance(envelope["checkpoint"]["b"], str)


def test_round_trip_con_tipos_no_json() -> None:
    """datetime y bytes sobreviven el viaje completo gracias al serde de LangGraph."""
    from datetime import datetime

    marca = datetime(2026, 10, 10, 12, 30, 0)
    saver = _saver()
    saver.put(
        _config(_thread()),
        _checkpoint(timestamp=marca, adjunto=b"\x00\x01"),
        _metadata(0),
        {},
    )
    tupla = saver.get_tuple(_config(_thread()))
    assert tupla is not None
    assert tupla.checkpoint["channel_values"] == {"timestamp": marca, "adjunto": b"\x00\x01"}


def test_ttl_se_pasa_al_port() -> None:
    """La caducidad la fija el saver (retención) y llega al almacén en cada escritura."""
    store = _PortConTtl()
    saver = _saver(store, ttl=3600)
    saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    assert store.ttl_ultimo == 3600


def test_list_sin_config_no_devuelve_nada() -> None:
    """El port no enumera conversaciones: listar exige `thread_id`."""
    saver = _saver()
    saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    assert list(saver.list(None)) == []


def test_list_devuelve_el_checkpoint_vigente() -> None:
    """`list` con el hilo devuelve el estado recién guardado."""
    saver = _saver()
    saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    tuplas = list(saver.list(_config(_thread())))
    assert len(tuplas) == 1
    assert tuplas[0].checkpoint["channel_values"] == {}


def test_list_respeta_limit_y_before() -> None:
    """`limit<=0` no devuelve nada y `before` descarta el vigente si es igual o menor."""
    saver = _saver()
    guardado = saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    assert list(saver.list(_config(_thread()), limit=0)) == []
    assert list(saver.list(_config(_thread()), before=guardado)) == []
    assert len(list(saver.list(_config(_thread()), limit=1))) == 1


def test_list_filtra_por_metadata() -> None:
    """El filtro de metadata compara pares clave-valor contra la metadata guardada."""
    saver = _saver()
    saver.put(_config(_thread()), _checkpoint(), _metadata(0), {})
    config = _config(_thread())
    assert list(saver.list(config, filter={"source": "loop"})) != []
    assert list(saver.list(config, filter={"source": "input"})) == []


def test_payload_corrompo_lanza_validation_error() -> None:
    """Un payload que no es un envelope del saver se rechaza tipado (sin excepción
    ajena)."""
    store = InMemoryMemoryStore()
    store.put(tenant_id=_TENANT, conversation_id=_CONVERSACION, payload="no es json")
    with pytest.raises(ValidationError):
        _saver(store).get_tuple(_config(_thread()))
    store.put(tenant_id=_TENANT, conversation_id=_CONVERSACION, payload="{}")
    with pytest.raises(ValidationError):
        _saver(store).get_tuple(_config(_thread()))


def test_versiones_asincronas_delegan_en_las_sincronas() -> None:
    """Las rutas `a*` (para `ainvoke`) devuelven lo mismo que sus equivalentes."""

    async def _corutina() -> None:
        tupla = await saver.aget_tuple(_config(_thread()))
        assert tupla is not None
        assert tupla.checkpoint["channel_values"] == {"reply": "hola"}
        await saver.aput_writes(
            _config(_thread(), str(tupla.checkpoint["id"])), [("llm", "v")], "t"
        )
        await saver.adelete_thread(_thread())

    saver = _saver()
    saver.put(_config(_thread()), _checkpoint(reply="hola"), _metadata(0), {})
    asyncio.run(_corutina())
    assert saver.get_tuple(_config(_thread())) is None
