"""Ejecutor del dataset de comportamiento de citas (Paso 5, Fase 5).

Recorre `datasets/appointments_behavior.json` punta a punta por el grafo real:
supervisor (clasificación, enrutado y router de pendientes) + especialista de citas
con dobles en memoria. El LLM doble devuelve las salidas guionizadas de cada caso y el
build falla si un caso crea una cita que debía quedar a la espera, si «sin hora» no
pide el dato o si la regla crítica de la hora produce invocaciones. Datos sintéticos;
el runner con modelo real llega en el Paso 14.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from adapters.in_memory import InMemoryDraftStore
from shared.contracts import AgentName, InboundMessage
from shared.contracts.pending import DraftStatus
from shared.ports import LLMMessage, LLMResult
from slices.appointments.application.graph import build_appointment_graph
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore
from slices.supervisor.application.graph import build_supervisor_graph

_RUTA_DATASET = Path(__file__).resolve().parent / "datasets" / "appointments_behavior.json"
_DATOS: dict[str, Any] = json.loads(_RUTA_DATASET.read_text(encoding="utf-8"))
CASOS: list[dict[str, Any]] = _DATOS["casos"]

TENANT = "Sede_Elite_01"
CONVERSACION = "whatsapp:57300999999"
BOTS_COMPLETOS: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
AHORA = datetime(2026, 3, 2, 8, 0)

_VIERNES = OpeningHoursDay(weekday=4, open_time="09:00", close_time="12:00")
_VENTANA_2026 = (datetime(2026, 1, 1), datetime(2026, 12, 31))


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
            system: Bloque de sistema recibido (se guarda para asertar la pista).
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
    """Grafo especialista doble: registra la invocación (no debe ocurrir aquí)."""

    def __init__(self) -> None:
        """Inicializa el registro de invocaciones."""
        self.calls: list[Any] = []

    def invoke(self, input: Any) -> dict[str, Any]:
        """Registra la entrada y devuelve su estado final simulado.

        Args:
            input: Estado que arma el supervisor para el especialista.

        Returns:
            `{"reply": ...}`.
        """
        self.calls.append(input)
        return {"reply": "respuesta del especialista no invocado"}


class _ConfirmerEspia:
    """ConfirmerPort doble: registra resoluciones (ninguna se espera en estos casos)."""

    def __init__(self) -> None:
        """Inicializa el registro de resoluciones."""
        self.calls: list[tuple[str, str]] = []

    def affirm(self, *, tenant_id: str, draft_id: str, payload_hash: str) -> None:
        """Registra la confirmación.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft confirmado.
            payload_hash: Hash confirmado.
        """
        self.calls.append(("affirm", draft_id))

    def deny(self, *, tenant_id: str, draft_id: str) -> None:
        """Registra el rechazo.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft rechazado.
        """
        self.calls.append(("deny", draft_id))

    def undo(self, *, tenant_id: str, draft_id: str) -> None:
        """Registra el deshacer.

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft deshecho.
        """
        self.calls.append(("undo", draft_id))


@dataclass
class _Resultado:
    """Salida del caso: estado final y dobles para las aserciones."""

    estado: Any
    llm: _FakeLLM
    citas: InMemoryAppointmentRepository
    drafts: InMemoryDraftStore
    confirmer: _ConfirmerEspia
    especialista_pedidos: _GrafoEspia


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
        customer_id="57300999999",
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


def _ejecutar(caso: dict[str, Any]) -> _Resultado:
    """Corre un caso completo por el supervisor y el especialista reales.

    Args:
        caso: Caso del dataset.

    Returns:
        Estado final y dobles para asertar.
    """
    reloj = _RelojFijo(AHORA)
    llm = _FakeLLM([_salida(item) for item in caso["llm"]])
    citas = InMemoryAppointmentRepository()
    drafts = InMemoryDraftStore(clock=reloj)
    grafo_citas = build_appointment_graph(
        llm=llm,
        repo=citas,
        clock=reloj,
        opening_hours=(_VIERNES,),
        drafts=drafts,
    )
    lector = CustomerContextTools(store=InMemoryCustomerContextStore(clock=reloj), clock=reloj)
    especialista_pedidos = _GrafoEspia()
    confirmer = _ConfirmerEspia()
    supervisor = build_supervisor_graph(
        llm=llm,
        context_reader=lector,
        allowed_bots=BOTS_COMPLETOS,
        appointments_graph=grafo_citas,
        orders_graph=especialista_pedidos,
        draft_store=InMemoryDraftStore(clock=reloj),
        confirmer=confirmer,
    )
    estado = supervisor.invoke({"message": _mensaje(caso), "history": _historial(caso)})
    return _Resultado(
        estado=estado,
        llm=llm,
        citas=citas,
        drafts=drafts,
        confirmer=confirmer,
        especialista_pedidos=especialista_pedidos,
    )


def _estado_draft(store: InMemoryDraftStore) -> str | None:
    """Estado del draft de la conversación del caso (activo o recién commiteado).

    Args:
        store: Store de drafts del especialista de citas.

    Returns:
        El valor del `DraftStatus` o `None` si no hubo draft.
    """
    activo = store.get_active(tenant_id=TENANT, conversation_id=CONVERSACION)
    if activo is not None:
        return activo.status.value
    deshacer = store.get_undoable(tenant_id=TENANT, conversation_id=CONVERSACION)
    return deshacer.status.value if deshacer is not None else None


@pytest.mark.parametrize("caso", CASOS, ids=[caso["id"] for caso in CASOS])
def test_caso_de_comportamiento(caso: dict[str, Any]) -> None:
    """Ejecuta un caso y verifica destino, efectos, draft, pista y llamadas al modelo."""
    resultado = _ejecutar(caso)
    esperado = caso["esperado"]
    estado = resultado.estado

    assert estado["routed"].target == esperado["target"]
    assert estado["reply"] == _salida(caso["llm"][-1]).strip()

    citas = list(
        resultado.citas.list_for_period(
            tenant_id=TENANT, start=_VENTANA_2026[0], end=_VENTANA_2026[1]
        )
    )
    assert len(citas) == esperado["creados"]
    assert _estado_draft(resultado.drafts) == esperado["draft_status"]

    assert len(resultado.llm.calls) == len(caso["llm"])
    system = resultado.llm.calls[-1]["system"]
    assert isinstance(system, str) and esperado["system_contiene"] in system

    assert resultado.confirmer.calls == []
    assert resultado.especialista_pedidos.calls == []


def test_el_estado_del_draft_es_un_estado_canonico() -> None:
    """Los `draft_status` del dataset son valores reales de la máquina de estados."""
    validos = {estado.value for estado in DraftStatus}
    for caso in CASOS:
        status = caso["esperado"]["draft_status"]
        assert status is None or status in validos
