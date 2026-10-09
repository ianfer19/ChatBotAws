"""Tests del router de drafts del supervisor: `resolve_pending` (ADR 0011.5)."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, ClassVar

import pytest

from adapters.in_memory import InMemoryDraftStore
from shared.contracts import CustomerContext, InboundMessage
from shared.contracts.pending import DraftStatus, PendingDraft, compute_payload_hash
from shared.errors import AppError, ToolError
from shared.ports import LLMMessage, LLMResult
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.graph import build_supervisor_graph
from slices.supervisor.application.nodes import resolve_pending, ruta_tras_pendiente
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.pending import (
    es_afirmativa,
    es_de_deshacer,
    es_negativa,
    respuesta_plantilla,
)
from slices.supervisor.domain.routing import saludo

TENANT = "Sede_Elite_01"
CLIENTE = "57300111111"
CONVERSACION = f"whatsapp:{CLIENTE}"
AHORA = datetime(2026, 3, 2, 12, 0)

JSON_PASS = '{"decision": "pass", "payload_hash": "x"}'
JSON_AFFIRM = '{"decision": "affirm", "payload_hash": "%s"}'
JSON_GREETING = '{"intent": "greeting", "confidence": 0.97}'

_PAYLOAD = {"op": "create", "items": [{"sku": "A-100", "quantity": 2}], "total": 36_000.0}
_HASH = compute_payload_hash(_PAYLOAD)


class _DraftNoCommiteable(AppError):
    """Simula el rechazo real del especialista (`DraftNotCommittable`)."""

    code: ClassVar[str] = "draft_not_committable"
    http_status: ClassVar[int] = 409


class _RelojFijo:
    """Reloj inyectable con hora fija para TTL y ventana de deshacer."""

    def __init__(self, ahora: datetime) -> None:
        """Guarda el instante que devolverá `now`.

        Args:
            ahora: Instante fijo del test.
        """
        self._ahora = ahora

    def now(self) -> datetime:
        """Devuelve el instante fijo del test.

        Returns:
            La hora configurada al construir el reloj.
        """
        return self._ahora


class _FakeLLM:
    """LLM doble: devuelve las salidas guionizadas en orden y registra cada llamada."""

    def __init__(self, salidas: list[str]) -> None:
        """Prepara la cola de salidas del doble.

        Args:
            salidas: Textos que devolverá `invoke`, uno por invocación.
        """
        self.salidas = list(salidas)
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
            messages: Turno recibido (se guarda tal cual para asertar).
            system: Bloque de sistema (se guarda para asertar el hash del draft).
            max_tokens: Tope de salida; el doble lo ignora.
            temperature: Muestreo; el doble lo ignora.

        Returns:
            `LLMResult` con el texto guionizado.
        """
        self.calls.append({"messages": list(messages), "system": system})
        texto = self.salidas.pop(0) if self.salidas else "{}"
        return LLMResult(text=texto)


class _LectorContexto:
    """Doble mínimo del `ContextReaderPort`: contexto fijo del tenant de prueba."""

    def get_customer_context(self, *, tenant_id: str, customer_id: str) -> CustomerContext | None:
        """Devuelve el contexto de juguete (el router no lo usa; `load_context` sí).

        Args:
            tenant_id: Comercio inyectado por el nodo desde el mensaje.
            customer_id: Cliente inyectado por el nodo desde el mensaje.

        Returns:
            Contexto congelado de ejemplo.
        """
        return CustomerContext(tenant_id=tenant_id, customer_id=customer_id, name="Ana")


class _EspecialistaEspia:
    """Doble del grafo de citas: registra la invocación (no debe ser llamado aquí)."""

    def __init__(self, reply: str = "respuesta del especialista") -> None:
        """Prepara el especialista con su respuesta de juguete.

        Args:
            reply: Texto de `reply` del estado final simulado.
        """
        self._reply = reply
        self.calls: list[Any] = []

    def invoke(self, input: Any) -> dict[str, Any]:
        """Registra la entrada y devuelve su estado final simulado.

        Args:
            input: Estado que el supervisor arma para el especialista.

        Returns:
            `{"reply": ...}`.
        """
        self.calls.append(input)
        return {"reply": self._reply}


class _ConfirmerEspia:
    """Doble del `ConfirmerPort`: registra las resoluciones y opcionalmente falla."""

    def __init__(self, *, falla: bool = False) -> None:
        """Prepara el doble.

        Args:
            falla: Si es `True`, cualquier operación lanza `_DraftNoCommiteable`.
        """
        self.falla = falla
        self.calls: list[tuple[str, str, str | None]] = []

    def affirm(self, *, tenant_id: str, draft_id: str, payload_hash: str) -> None:
        """Registra la confirmación (o falla si el doble está en modo de fallo).

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft confirmado.
            payload_hash: Hash exacto confirmado.

        Raises:
            _DraftNoCommiteable: Si el doble está en modo de fallo.
        """
        if self.falla:
            raise _DraftNoCommiteable("el draft ya no admite cambios")
        self.calls.append(("affirm", draft_id, payload_hash))

    def deny(self, *, tenant_id: str, draft_id: str) -> None:
        """Registra el rechazo (o falla si el doble está en modo de fallo).

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft rechazado.

        Raises:
            _DraftNoCommiteable: Si el doble está en modo de fallo.
        """
        if self.falla:
            raise _DraftNoCommiteable("el draft ya no admite cambios")
        self.calls.append(("deny", draft_id, None))

    def undo(self, *, tenant_id: str, draft_id: str) -> None:
        """Registra el deshacer (o falla si el doble está en modo de fallo).

        Args:
            tenant_id: Comercio dueño del draft.
            draft_id: Draft deshecho.

        Raises:
            _DraftNoCommiteable: Si el doble está en modo de fallo.
        """
        if self.falla:
            raise _DraftNoCommiteable("el draft ya no admite cambios")
        self.calls.append(("undo", draft_id, None))


def _mensaje(texto: str) -> InboundMessage:
    """Mensaje normalizado del tenant de prueba (ids ya resueltos por el gateway).

    Args:
        texto: Texto del cliente.

    Returns:
        `InboundMessage` de whatsapp con `conversation_id` compuesto estándar.
    """
    return InboundMessage(
        tenant_id=TENANT,
        correlation_id="corr-1",
        channel="whatsapp",
        customer_id=CLIENTE,
        message_id="m-1",
        timestamp=AHORA,
        text=texto,
    )


def _historial() -> list[LLMMessage]:
    """Ventana de un turno previo (obligatoria en el grafo completo).

    Returns:
        Lista con dos mensajes de ejemplo.
    """
    return [
        LLMMessage(role="assistant", content="Hola, ¿en qué te ayudo?"),
        LLMMessage(role="user", content="Quería preguntar algo"),
    ]


def _turno(texto: str) -> SupervisorState:
    """Estado de un turno con historial para el router.

    Args:
        texto: Texto del cliente.

    Returns:
        Estado listo para `resolve_pending`.
    """
    return SupervisorState(message=_mensaje(texto), history=_historial())


def _draft(
    status: DraftStatus = DraftStatus.AWAITING_CONFIRMATION,
    *,
    expires_at: datetime | None = None,
    undo_until: datetime | None = None,
) -> PendingDraft:
    """Draft de pedido de prueba con su hash canónico calculado.

    Args:
        status: Estado inicial del draft.
        expires_at: TTL del draft (24 h por defecto).
        undo_until: Ventana de deshacer (solo relevante en `COMMITTED`).

    Returns:
        `PendingDraft` listo para guardar sin violar las invariantes del store.
    """
    return PendingDraft(
        draft_id="drf-1",
        tenant_id=TENANT,
        conversation_id=CONVERSACION,
        kind="order",
        status=status,
        payload=dict(_PAYLOAD),
        total=36_000.0,
        payload_hash=_HASH,
        correlation_id="corr-1",
        created_at=AHORA - timedelta(hours=1),
        expires_at=expires_at or AHORA + timedelta(hours=23),
        undo_until=undo_until,
    )


def _store_con(draft: PendingDraft) -> InMemoryDraftStore:
    """Store con el draft ya persistido (secuencia legal para `COMMITTED`).

    Args:
        draft: Draft a persistir; si es `COMMITTED`, primero se guarda su previo
            `AUTO_APPROVED` con el mismo id (invariante del store).

    Returns:
        Store listo para el test.
    """
    store = InMemoryDraftStore(clock=_RelojFijo(AHORA))
    if draft.status is DraftStatus.COMMITTED:
        previo = draft.model_copy(update={"status": DraftStatus.AUTO_APPROVED})
        store.save(tenant_id=TENANT, draft=previo)
    store.save(tenant_id=TENANT, draft=draft)
    return store


def _deps(
    llm: _FakeLLM,
    *,
    store: InMemoryDraftStore | None = None,
    confirmer: _ConfirmerEspia | None = None,
    con_router: bool = True,
) -> Deps:
    """Dependencias del supervisor para llamar al nodo suelto.

    Args:
        llm: Doble guionizado del modelo.
        store: Store con el draft del test (si hace falta).
        confirmer: Doble del confirmer (si hace falta).
        con_router: Si es `False`, no inyecta store ni confirmer (retrocompatibilidad).

    Returns:
        Dependencias listas para `resolve_pending`.
    """
    return Deps(
        llm=llm,
        context_reader=_LectorContexto(),
        allowed_bots=frozenset({"sales", "appointments", "orders", "faq"}),
        appointments_graph=_EspecialistaEspia(),
        draft_store=store if con_router else None,
        confirmer=confirmer if con_router else None,
    )


def _grafo(
    salidas: list[str],
    *,
    store: InMemoryDraftStore,
    confirmer: _ConfirmerEspia,
) -> tuple[Any, _FakeLLM, _EspecialistaEspia]:
    """Grafo del supervisor compilado con el router de pendientes inyectado.

    Args:
        salidas: Textos que devolverá el LLM, uno por invocación.
        store: Store de drafts del test.
        confirmer: Doble del confirmer del test.

    Returns:
        Tupla (grafo, doble de LLM, especialista espía).
    """
    llm = _FakeLLM(salidas)
    especialista = _EspecialistaEspia()
    grafo = build_supervisor_graph(
        llm=llm,
        context_reader=_LectorContexto(),
        allowed_bots=frozenset({"sales", "appointments", "orders", "faq"}),
        appointments_graph=especialista,
        draft_store=store,
        confirmer=confirmer,
    )
    return grafo, llm, especialista


# --------------------------------------------------------------------- dominio exacto


@pytest.mark.parametrize("texto", ["sí", "SI", "Sí.", "¡Ok!", "confirmo"])
def test_afirmativas_exactas(texto: str) -> None:
    """Toda variante razonable de «sí» normaliza al conjunto afirmativo."""
    assert es_afirmativa(texto)


@pytest.mark.parametrize("texto", ["no", "No, gracias", "mejor no.", "cancelar!"])
def test_negativas_exactas(texto: str) -> None:
    """Toda variante razonable de «no» normaliza al conjunto negativo."""
    assert es_negativa(texto)


@pytest.mark.parametrize("texto", ["cancelar", "Deshacer.", "anula"])
def test_deshacer_exacto(texto: str) -> None:
    """El conjunto de deshacer reconoce sus variantes exactas."""
    assert es_de_deshacer(texto)


def test_una_frase_larga_no_es_respuesta_exacta() -> None:
    """La clasificación exacta es de igualdad completa: nada de subcadenas."""
    assert not es_afirmativa("sí, pero quiero cambiar la cantidad")
    assert not es_negativa("no sé, dime tú")


# ------------------------------------------------------------------- nodo resolve_pending


def test_si_exacto_confirma_sin_llm() -> None:
    """«Sí» exacto → `affirm` con el hash del draft, plantilla y cero llamadas al LLM."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([])
    estado = resolve_pending(_turno("¡Sí!"), deps=_deps(llm, store=store, confirmer=confirmer))
    assert confirmer.calls == [("affirm", "drf-1", _HASH)]
    assert estado["reply"] == respuesta_plantilla("affirmed")
    assert estado["pending_outcome"] == "affirmed"
    assert llm.calls == []
    assert ruta_tras_pendiente(estado) == "end"


def test_no_exacto_cancela_sin_llm() -> None:
    """«No» exacto → `deny` del draft a la espera, sin invocar al clasificador."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([])
    estado = resolve_pending(
        _turno("no, gracias"), deps=_deps(llm, store=store, confirmer=confirmer)
    )
    assert confirmer.calls == [("deny", "drf-1", None)]
    assert estado["reply"] == respuesta_plantilla("denied")
    assert llm.calls == []


def test_respuesta_libre_usa_el_llm_que_ecoa_el_hash() -> None:
    """Sin match exacto, el LLM de respaldo clasifica y su eco del hash debe coincidir."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([JSON_AFFIRM % _HASH])
    estado = resolve_pending(
        _turno("confirmalo porfa"), deps=_deps(llm, store=store, confirmer=confirmer)
    )
    assert confirmer.calls == [("affirm", "drf-1", _HASH)]
    assert estado["pending_outcome"] == "affirmed"
    assert len(llm.calls) == 1
    system = llm.calls[0]["system"]
    assert isinstance(system, str) and _HASH in system


def test_hash_desfasado_no_confirma_y_pasa_al_agente() -> None:
    """El eco de un hash distinto se ignora: nada se confirma y el turno sigue normal."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([JSON_AFFIRM % "hash-de-otro-contenido"])
    estado = resolve_pending(
        _turno("dale, confirma"), deps=_deps(llm, store=store, confirmer=confirmer)
    )
    assert confirmer.calls == []
    assert "reply" not in estado
    assert "pending_outcome" not in estado
    assert ruta_tras_pendiente(estado) == "classify"
    assert len(llm.calls) == 1


def test_json_ilegible_dos_veces_pasa_al_agente() -> None:
    """Dos salidas que no son JSON → el router no resuelve y no rompe el turno."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM(["no soy json", "tampoco lo soy"])
    estado = resolve_pending(_turno("eh"), deps=_deps(llm, store=store, confirmer=confirmer))
    assert confirmer.calls == []
    assert "reply" not in estado
    assert len(llm.calls) == 2


def test_fallo_del_llm_pasa_al_agente() -> None:
    """Bedrock caído durante el respaldo → degradación a flujo normal, sin excepción."""
    store = _store_con(_draft())

    class _LLMFalla(_FakeLLM):
        """Doble que simula proveedor caído en todas las invocaciones."""

        def invoke(
            self,
            *,
            messages: Sequence[LLMMessage],
            system: str | None = None,
            max_tokens: int | None = None,
            temperature: float | None = None,
        ) -> LLMResult:
            """Lanza `ToolError` como haría el adapter real.

            Args:
                messages: Ignorado.
                system: Ignorado.
                max_tokens: Ignorado.
                temperature: Ignorado.

            Returns:
                Nunca devuelve: siempre lanza.

            Raises:
                ToolError: Simulando a Bedrock caído.
            """
            raise ToolError("bedrock no responde")

    confirmer = _ConfirmerEspia()
    estado = resolve_pending(
        _turno("confirmalo"), deps=_deps(_LLMFalla([]), store=store, confirmer=confirmer)
    )
    assert confirmer.calls == []
    assert "reply" not in estado


def test_draft_expirado_no_se_confirma() -> None:
    """Un draft con TTL vencido ya no ocupa la ranura: «sí» ya no confirma nada."""
    store = _store_con(_draft(expires_at=AHORA - timedelta(minutes=1)))
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([])
    estado = resolve_pending(_turno("sí"), deps=_deps(llm, store=store, confirmer=confirmer))
    assert confirmer.calls == []
    assert "reply" not in estado
    assert llm.calls == []
    assert ruta_tras_pendiente(estado) == "classify"


def test_cancelar_dentro_de_la_ventana_deshace_el_pedido() -> None:
    """«Cancelar» exacto sobre un draft `COMMITTED` con ventana abierta → `undo`."""
    draft = _draft(status=DraftStatus.COMMITTED, undo_until=AHORA + timedelta(minutes=20))
    store = _store_con(draft)
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([])
    estado = resolve_pending(_turno("cancelar"), deps=_deps(llm, store=store, confirmer=confirmer))
    assert confirmer.calls == [("undo", "drf-1", None)]
    assert estado["reply"] == respuesta_plantilla("undoed")
    assert estado["pending_outcome"] == "undoed"
    assert llm.calls == []


def test_cancelar_fuera_de_la_ventana_no_deshace() -> None:
    """Pasada la ventana de deshacer, el pedido ya commiteado no se toca."""
    draft = _draft(status=DraftStatus.COMMITTED, undo_until=AHORA - timedelta(minutes=1))
    store = _store_con(draft)
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([])
    estado = resolve_pending(_turno("cancelar"), deps=_deps(llm, store=store, confirmer=confirmer))
    assert confirmer.calls == []
    assert "reply" not in estado


def test_sin_draft_la_respuesta_pasa_al_agente() -> None:
    """Conversación sin pendientes: el router ni siquiera consulta al confirmer."""
    store = InMemoryDraftStore(clock=_RelojFijo(AHORA))
    confirmer = _ConfirmerEspia()
    llm = _FakeLLM([])
    estado = resolve_pending(_turno("sí"), deps=_deps(llm, store=store, confirmer=confirmer))
    assert confirmer.calls == []
    assert "reply" not in estado
    assert llm.calls == []


def test_router_no_inyectado_es_retrocompatible() -> None:
    """Sin store ni confirmer (composición previa) el turno pasa intacto."""
    llm = _FakeLLM([])
    estado = resolve_pending(_turno("sí"), deps=_deps(llm, con_router=False))
    assert "reply" not in estado
    assert llm.calls == []


def test_error_del_confirmer_degrada_al_agente_con_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un confirmer que rechaza (hash, estado, ventana) degrada con warn, sin excepción."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia(falla=True)
    llm = _FakeLLM([])
    with caplog.at_level("WARNING"):
        estado = resolve_pending(_turno("sí"), deps=_deps(llm, store=store, confirmer=confirmer))
    assert "reply" not in estado
    assert "pending_outcome" not in estado
    assert any("supervisor.pending_resolution_failed" in r.getMessage() for r in caplog.records)
    assert ruta_tras_pendiente(estado) == "classify"


# ------------------------------------------------------------------- grafo end-to-end


def test_e2e_si_confirma_sin_llm_ni_clasificador() -> None:
    """Turno completo: el «sí» cierra el draft con plantilla y jamás llega a `classify`."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia()
    grafo, llm, especialista = _grafo([], store=store, confirmer=confirmer)
    estado = grafo.invoke(_turno("sí"))
    assert confirmer.calls == [("affirm", "drf-1", _HASH)]
    assert estado["reply"] == respuesta_plantilla("affirmed")
    assert estado["pending_outcome"] == "affirmed"
    assert "routed" not in estado
    assert llm.calls == []
    assert especialista.calls == []


def test_e2e_saludo_intacto_aunque_haya_un_draft_esperando() -> None:
    """Regresión: con draft activo, «hola» sigue siendo saludo propio del supervisor."""
    store = _store_con(_draft())
    confirmer = _ConfirmerEspia()
    grafo, llm, especialista = _grafo([JSON_PASS, JSON_GREETING], store=store, confirmer=confirmer)
    estado = grafo.invoke(_turno("hola, buenos días"))
    assert estado["reply"] == saludo(TENANT)
    assert estado["target"] == "supervisor"
    assert "pending_outcome" not in estado
    assert confirmer.calls == []
    assert especialista.calls == []
    assert len(llm.calls) == 2


def test_e2e_sin_router_el_grafo_no_cambia() -> None:
    """Composición sin router: el clasificador ve el turno como siempre (un solo LLM)."""
    llm = _FakeLLM([JSON_GREETING])
    grafo = build_supervisor_graph(
        llm=llm,
        context_reader=_LectorContexto(),
        allowed_bots=frozenset({"sales", "appointments", "orders", "faq"}),
        appointments_graph=_EspecialistaEspia(),
    )
    estado = grafo.invoke(_turno("hola, buenos días"))
    assert estado["reply"] == saludo(TENANT)
    assert len(llm.calls) == 1
