"""Ejecutor del dataset de comportamiento del agente faq (Paso 7).

Recorre `datasets/faq_behavior.json` punta a punta por el grafo real: supervisor
(clasificación y enrutado) + grafo faq con el almacén vectorial en memoria
sembrado con el conocimiento de dos comercios. El LLM doble devuelve las salidas
guionizadas de cada caso y el build falla si un caso inventa una respuesta sin
evidencia, si la respuesta no cita la fuente esperada o si un comercio ve chunks
del otro. Datos sintéticos; el runner con modelo real llega en el Paso 14.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from adapters.in_memory import InMemoryEmbeddings, InMemoryVectorStore
from shared.contracts import AgentName, InboundMessage
from shared.ports import LLMMessage, LLMResult, VectorRecord
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore
from slices.knowledge_rag.application.graph import build_faq_graph
from slices.supervisor.application.graph import build_supervisor_graph

_RUTA_DATASET = Path(__file__).resolve().parent / "datasets" / "faq_behavior.json"
_DATOS: dict[str, Any] = json.loads(_RUTA_DATASET.read_text(encoding="utf-8"))
CASOS: list[dict[str, Any]] = _DATOS["casos"]

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Sede_Otro_02"
BOTS: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
AHORA = datetime(2026, 3, 2, 12, 0)

_HORARIO_A = "El horario de apertura es de lunes a sabado de 8:00 a 20:00."
_HORARIO_B = "El horario de apertura es de lunes a viernes de 9:00 a 18:00."
_SALON_A = "El salon principal admite ochenta personas con decoracion incluida."
_SALON_B = "El salon principal admite ciento veinte personas con decoracion incluida."


class _RelojFijo:
    """Reloj fijo con el que corren todos los dobles del caso."""

    def __init__(self, ahora: datetime) -> None:
        """Guarda el instante fijo.

        Args:
            ahora: Instante del test.
        """
        self._ahora = ahora

    def now(self) -> datetime:
        """Devuelve el instante fijo.

        Returns:
            La hora configurada.
        """
        return self._ahora


class _FakeLLM:
    """LLM doble: reparte las salidas guionizadas en orden y falla si sobran llamadas."""

    def __init__(self, salidas: list[str]) -> None:
        """Prepara la cola de salidas del doble.

        Args:
            salidas: Textos que devolverá `invoke`, uno por invocación.
        """
        self._salidas = list(salidas)
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self,
        *,
        messages: Sequence[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Devuelve la siguiente salida guionizada y registra la llamada.

        Args:
            messages: Turno recibido (se guarda para asertar).
            system: Bloque de sistema recibido (se guarda para asertar la evidencia).
            max_tokens: Tope de salida; el doble lo ignora.
            temperature: Muestreo; el doble lo ignora.

        Returns:
            `LLMResult` con el texto guionizado.

        Raises:
            AssertionError: Si el turno pide más llamadas de las guionizadas.
        """
        assert self._salidas, "el turno hizo más llamadas al LLM de las guionizadas"
        self.calls.append({"messages": list(messages), "system": system})
        return LLMResult(text=self._salidas.pop(0))


class _GrafoEspia:
    """Grafo de citas doble: registra la invocación (no debe ocurrir aquí)."""

    def __init__(self) -> None:
        """Inicializa el registro de invocaciones."""
        self.calls: list[Any] = []

    def invoke(self, input: Any) -> dict[str, Any]:
        """Registra la entrada y devuelve un estado simulado.

        Args:
            input: Estado que arma el supervisor para el especialista.

        Returns:
            `{"reply": ...}`.
        """
        self.calls.append(input)
        return {"reply": "respuesta del especialista no invocado"}


def _record(
    identificador: str, tenant: str, texto: str, *, titulo: str, fuente: str
) -> VectorRecord:
    """Registro vectorial con el embedding calculado por el doble en memoria.

    Args:
        identificador: Id estable del chunk dentro del comercio.
        tenant: Comercio dueño del registro.
        texto: Contenido del chunk.
        titulo: Título de la fuente (para la cita).
        fuente: Id de la fuente en el backend.

    Returns:
        Registro listo para el almacén.
    """
    vector = list(InMemoryEmbeddings().embed(texts=[texto])[0])
    return VectorRecord(
        id=identificador,
        tenant_id=tenant,
        text=texto,
        vector=vector,
        metadata={"source_type": "faq", "source_id": fuente, "title": titulo},
    )


def _almacen() -> InMemoryVectorStore:
    """Almacén sembrado con el conocimiento de los dos comercios del dataset.

    Returns:
        Almacén con horarios y capacidad de `TENANT` y `OTRO_TENANT`.
    """
    store = InMemoryVectorStore()
    store.upsert(
        records=[
            _record("h-a", TENANT, _HORARIO_A, titulo="FAQ Horario", fuente="faq-1"),
            _record("s-a", TENANT, _SALON_A, titulo="FAQ Salon", fuente="faq-2"),
            _record("h-b", OTRO_TENANT, _HORARIO_B, titulo="FAQ Horario", fuente="faq-1"),
            _record("s-b", OTRO_TENANT, _SALON_B, titulo="FAQ Salon", fuente="faq-2"),
        ]
    )
    return store


def _mensaje(caso: dict[str, Any]) -> InboundMessage:
    """Mensaje normalizado del caso (el tenant siempre viene del dataset).

    Args:
        caso: Caso del dataset.

    Returns:
        `InboundMessage` sintético con los ids resueltos.
    """
    entrada = caso["entrada"]
    return InboundMessage(
        tenant_id=entrada["tenant"],
        correlation_id=f"corr-{caso['id']}",
        channel="whatsapp",
        emitter_id="1000",
        customer_id="57300222222",
        message_id=f"m-{caso['id']}",
        timestamp=AHORA,
        text=entrada["mensaje"],
    )


def _historial(caso: dict[str, Any]) -> list[LLMMessage]:
    """Ventana de historial declarada en el caso (puede ser vacía, pero presente).

    Args:
        caso: Caso del dataset.

    Returns:
        Mensajes del historial ya tipados.
    """
    return [LLMMessage.model_validate(item) for item in caso["entrada"].get("historial", [])]


@dataclass
class _Resultado:
    """Salida del caso: estado final y dobles para las aserciones."""

    estado: Any
    llm: _FakeLLM
    especialista_citas: _GrafoEspia


def _ejecutar(caso: dict[str, Any]) -> _Resultado:
    """Corre un caso completo por el supervisor y el grafo faq reales.

    Args:
        caso: Caso del dataset.

    Returns:
        Estado final y dobles para asertar.
    """
    reloj = _RelojFijo(AHORA)
    llm = _FakeLLM([_salida(item) for item in caso["llm"]])
    grafo_faq = build_faq_graph(llm=llm, embeddings=InMemoryEmbeddings(), store=_almacen())
    lector = CustomerContextTools(store=InMemoryCustomerContextStore(clock=reloj), clock=reloj)
    especialista_citas = _GrafoEspia()
    supervisor = build_supervisor_graph(
        llm=llm,
        context_reader=lector,
        allowed_bots=BOTS,
        appointments_graph=especialista_citas,
        faq_graph=grafo_faq,
    )
    estado = supervisor.invoke({"message": _mensaje(caso), "history": _historial(caso)})
    return _Resultado(estado=estado, llm=llm, especialista_citas=especialista_citas)


def _salida(elemento: Any) -> str:
    """Convierte una salida del dataset en el texto crudo que vería el nodo.

    Args:
        elemento: Cadena literal u objeto JSON del dataset.

    Returns:
        El texto de la salida del modelo.
    """
    if isinstance(elemento, str):
        return elemento
    return json.dumps(elemento, ensure_ascii=False)


@pytest.mark.parametrize("caso", CASOS, ids=[caso["id"] for caso in CASOS])
def test_caso_de_comportamiento(caso: dict[str, Any]) -> None:
    """Ejecuta un caso y verifica destino, reply, llamadas al modelo y evidencia."""
    resultado = _ejecutar(caso)
    esperado = caso["esperado"]
    estado = resultado.estado

    assert estado["routed"].target == esperado["target"]
    assert estado["reply"] == esperado["reply"]
    assert len(resultado.llm.calls) == esperado["llm_llamadas"]

    if "system_contiene" in esperado:
        system = resultado.llm.calls[-1]["system"]
        assert isinstance(system, str)
        assert esperado["system_contiene"] in system
    if "system_no_contiene" in esperado:
        system = resultado.llm.calls[-1]["system"]
        assert isinstance(system, str)
        assert esperado["system_no_contiene"] not in system

    assert resultado.especialista_citas.calls == []


def test_el_dataset_cubre_los_casos_obligatorios() -> None:
    """Los ids de regresión de `agent_evals/README.md` existen en el dataset."""
    identificadores = {caso["id"] for caso in CASOS}
    assert {"grounding_01", "tenant_isolation_01"} <= identificadores


def test_los_tenants_del_dataset_son_los_del_almacen() -> None:
    """Cada caso pregunta a un comercio sembrado: el aislamiento se puede probar."""
    sembrados = {caso["entrada"]["tenant"] for caso in CASOS}
    assert sembrados == {TENANT, OTRO_TENANT}
