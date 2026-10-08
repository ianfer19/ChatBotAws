"""Tests del kernel: los ports son Protocol y los dobles los satisfacen (shared/ports)."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from shared.errors import ValidationError
from shared.ports import (
    ClockPort,
    EventBusPort,
    LLMMessage,
    LLMPort,
    LLMResult,
    MemoryStorePort,
    VectorHit,
    VectorRecord,
    VectorStorePort,
)


class _FakeClock:
    """Reloj controlado: siempre devuelve el instante fijado."""

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class _FakeLLM:
    """Modelo fijo para tests: sin red ni tokens, con la firma Converse del port."""

    def invoke(
        self,
        *,
        messages: Sequence[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        del max_tokens, temperature
        ultimo = messages[-1].content if messages else ""
        prefijo = f"[{system}] " if system else ""
        return LLMResult(text=f"{prefijo}respuesta a: {ultimo}", stop_reason="end_turn")


class _FakeVectorStore:
    """Almacén vectorial en memoria: solo busca lo que se insertó con el mismo tenant."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], VectorRecord] = {}

    def upsert(self, *, records: Sequence[VectorRecord]) -> None:
        for record in records:
            self._records[(record.tenant_id, record.id)] = record

    def search(
        self, *, vector: Sequence[float], tenant_id: str, limit: int = 5
    ) -> Sequence[VectorHit]:
        del vector
        hits = [
            VectorHit(
                id=record.id,
                tenant_id=record.tenant_id,
                text=record.text,
                score=1.0,
                metadata=record.metadata,
            )
            for (stored_tenant, _), record in self._records.items()
            if stored_tenant == tenant_id
        ]
        return hits[:limit]

    def delete(self, *, tenant_id: str, ids: Sequence[str]) -> None:
        for record_id in ids:
            self._records.pop((tenant_id, record_id), None)


class _FakeMemoryStore:
    """Almacén de estado por conversación: diccionario con la clave del port."""

    def __init__(self) -> None:
        self._payloads: dict[tuple[str, str], str] = {}

    def put(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        payload: str,
        ttl_seconds: int | None = None,
    ) -> None:
        del ttl_seconds
        if not tenant_id or not conversation_id:
            raise ValidationError("faltan tenant_id o conversation_id")
        self._payloads[(tenant_id, conversation_id)] = payload

    def get(self, *, tenant_id: str, conversation_id: str) -> str | None:
        return self._payloads.get((tenant_id, conversation_id))

    def delete(self, *, tenant_id: str, conversation_id: str) -> None:
        self._payloads.pop((tenant_id, conversation_id), None)


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
    assert isinstance(_FakeVectorStore(), VectorStorePort)
    assert isinstance(_FakeMemoryStore(), MemoryStorePort)
    assert isinstance(_FakeBus(), EventBusPort)


def test_dobles_tipados_cumplen_la_firma_estructural() -> None:
    """mypy verifica la firma completa de los dobles al asignarlos al tipo del port."""
    llm: LLMPort = _FakeLLM()
    vector: VectorStorePort = _FakeVectorStore()
    memoria: MemoryStorePort = _FakeMemoryStore()
    assert isinstance(llm, LLMPort)
    assert isinstance(vector, VectorStorePort)
    assert isinstance(memoria, MemoryStorePort)


def test_clase_sin_la_firma_no_satisface_el_port() -> None:
    """`isinstance` del protocolo distingue dobles incompletos."""
    assert not isinstance(_NotAPort(), ClockPort)
    assert not isinstance(_NotAPort(), LLMPort)
    assert not isinstance(_NotAPort(), VectorStorePort)
    assert not isinstance(_NotAPort(), MemoryStorePort)
    assert not isinstance(_NotAPort(), EventBusPort)


def test_reloj_falso_devuelve_el_instante_fijado() -> None:
    """El dominio verá siempre el mismo reloj en el test (sin dormir ni monkeypatch)."""
    instant = datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
    assert _FakeClock(instant).now() == instant


def test_llm_falso_devuelve_texto_y_metadatos() -> None:
    """El doble cumple la firma Converse: historial + system -> `LLMResult`."""
    resultado = _FakeLLM().invoke(
        messages=[LLMMessage(role="user", content="hola")],
        system="eres útil",
    )
    assert resultado.text == "[eres útil] respuesta a: hola"
    assert resultado.stop_reason == "end_turn"


def test_llm_rechaza_roles_invalidos_y_contenido_vacio() -> None:
    """Los tipos del port no dejan pasar mensajes que Converse rechazaría."""
    with pytest.raises(PydanticValidationError):
        LLMMessage(role="system", content="hola")  # type: ignore[arg-type]
    with pytest.raises(PydanticValidationError):
        LLMMessage(role="user", content="")


def test_llm_result_es_inmutable_y_sin_campos_extra() -> None:
    """El resultado del modelo no se puede alterar tras leerse ni recibir campos ajenos."""
    resultado = LLMResult(text="ok")
    with pytest.raises(PydanticValidationError):
        resultado.text = "otro"
    with pytest.raises(PydanticValidationError):
        LLMResult(text="ok", model_id="claude")  # type: ignore[call-arg]


def test_almacen_vectorial_aisla_por_tenant() -> None:
    """Un chunk indexado por un comercio no lo ve otro (búsqueda filtrada por tenant)."""
    store = _FakeVectorStore()
    store.upsert(
        records=[
            VectorRecord(
                id="c1",
                tenant_id="Sede_Elite_01",
                text="abrimos de 8 a 20",
                vector=[0.1, 0.2],
            )
        ]
    )
    mismo = store.search(vector=[0.1, 0.2], tenant_id="Sede_Elite_01")
    otro = store.search(vector=[0.1, 0.2], tenant_id="Otro_Comercio_01")
    assert [hit.id for hit in mismo] == ["c1"]
    assert otro == []


def test_almacen_de_memoria_guarda_y_borra_por_conversacion() -> None:
    """El estado de una conversación sobrevive entre turnos y se puede purgar."""
    store = _FakeMemoryStore()
    store.put(tenant_id="t1", conversation_id="c1", payload='{"turno":1}')
    assert store.get(tenant_id="t1", conversation_id="c1") == '{"turno":1}'
    assert store.get(tenant_id="t2", conversation_id="c1") is None
    store.delete(tenant_id="t1", conversation_id="c1")
    assert store.get(tenant_id="t1", conversation_id="c1") is None


def test_almacen_de_memoria_exige_claves() -> None:
    """Sin tenant o sin conversación no se escribe nada (partición obligatoria)."""
    store = _FakeMemoryStore()
    with pytest.raises(ValidationError):
        store.put(tenant_id="", conversation_id="c1", payload="{}")


def test_record_vectorial_rechaza_vectores_vacios() -> None:
    """Un registro sin embedding no es indexable: el port lo impone en el tipo."""
    with pytest.raises(PydanticValidationError):
        VectorRecord(
            id="c1",
            tenant_id="t1",
            text="algo",
            vector=[],
        )


def test_bus_falso_guarda_evento_y_payload() -> None:
    """El doble del bus retiene el nombre y una copia inmutable-en-el-hecho del payload."""
    bus = _FakeBus()
    bus.publish("inbound.message", {"tenant_id": "Sede_Elite_01"})
    assert bus.events == [("inbound.message", {"tenant_id": "Sede_Elite_01"})]
