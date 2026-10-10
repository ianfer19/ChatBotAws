"""Tests del grafo de respuestas de conocimiento (faq), ROADMAP Paso 7.

Cubren las dos ramas del grafo: respuesta fundamentada (la tool entrega evidencia
del propio tenant y el LLM redacta con el bloque de evidencia en el system) y
fallback honesto (sin evidencia o con el almacén caído: mensaje de dominio y
**cero** invocaciones al modelo). El aislamiento por tenant se verifica en el grafo
completo: la misma pregunta sobre el mismo almacén solo ve los chunks del comercio
del turno.
"""

from collections.abc import Sequence
from typing import Any

from adapters.in_memory import InMemoryEmbeddings, InMemoryVectorStore
from shared.errors import ToolError
from shared.ports import LLMMessage, LLMResult, VectorHit, VectorRecord, VectorStorePort
from slices.knowledge_rag.application.deps import Deps
from slices.knowledge_rag.application.graph import build_faq_graph
from slices.knowledge_rag.application.nodes import fallback, retrieve, ruta_tras_recuperar
from slices.knowledge_rag.application.prompts import TAREA_RESPONDER, load_system_prompt
from slices.knowledge_rag.application.state import AgentState
from slices.knowledge_rag.application.tools import KnowledgeTools
from slices.knowledge_rag.domain.rules import mensaje_fallback

TENANT = "Sede_Elite_01"
OTRO_TENANT = "Sede_Otro_02"
CORRELACION = "corr-faq-1"

_HORARIO_A = "El horario de apertura es de lunes a sabado de 8:00 a 20:00."
_HORARIO_B = "El horario de apertura es de lunes a viernes de 9:00 a 18:00."
_SALON_A = "El salon principal admite ochenta personas con decoracion incluida."
_SALON_B = "El salon principal admite ciento veinte personas con decoracion incluida."

_PREGUNTA_HORARIO = "¿Cual es el horario de apertura?"
_PREGUNTA_SIN_RESPUESTA = "¿Hacen envios a domicilio?"


class _FakeLLM:
    """LLM doble: devuelve las salidas guionizadas en orden y registra cada llamada."""

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


class _AlmacenCaido:
    """Doble de `VectorStorePort` cuya búsqueda siempre falla (Aurora caída)."""

    def upsert(self, *, records: Sequence[VectorRecord]) -> None:
        """Ignora la escritura: este doble solo se usa para buscar."""
        return None

    def search(
        self, *, vector: Sequence[float], tenant_id: str, limit: int = 5
    ) -> Sequence[VectorHit]:
        """Falla como el adapter real cuando la base no responde.

        Args:
            vector: Embedding de la consulta.
            tenant_id: Comercio del turno.
            limit: Máximo de resultados.

        Returns:
            Nunca devuelve: siempre lanza.

        Raises:
            ToolError: Simula el fallo de la base.
        """
        raise ToolError("aurora no responde")

    def delete(self, *, tenant_id: str, ids: Sequence[str]) -> None:
        """Ignora el borrado: este doble solo se usa para buscar."""
        return None


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
    """Almacén con el conocimiento de dos comercios (la peor caso de aislamiento).

    Returns:
        Almacén sembrado con horarios y capacidad de `TENANT` y `OTRO_TENANT`.
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


def _turno(
    texto: str,
    *,
    tenant: str = TENANT,
    historial: list[LLMMessage] | None = None,
) -> AgentState:
    """Estado de un turno tal como lo arma `route_faq` desde el supervisor.

    Args:
        texto: Pregunta del cliente.
        tenant: Comercio del turno (contexto resuelto, nunca del LLM).
        historial: Ventana de historial; `None` deja el turno sin ella.

    Returns:
        Estado listo para `invoke` del grafo.
    """
    estado = AgentState(tenant_id=tenant, correlation_id=CORRELACION, user_message=texto)
    if historial is not None:
        estado["history"] = historial
    return estado


def _historial() -> list[LLMMessage]:
    """Ventana de un turno previo para asertar que viaja al modelo.

    Returns:
        Lista con un saludo previo.
    """
    return [LLMMessage(role="assistant", content="Hola, ¿en qué te ayudo?")]


def _grafo(
    salidas: list[str], *, store: VectorStorePort | None = None
) -> tuple[Any, _FakeLLM, VectorStorePort]:
    """Grafo faq compilado con dobles a la vista.

    Args:
        salidas: Textos que devolverá el LLM, uno por invocación.
        store: Almacén a usar; `None` crea el sembrado de dos comercios.

    Returns:
        Tupla (grafo, llm, almacén).
    """
    llm = _FakeLLM(salidas)
    almacén = store if store is not None else _almacen()
    grafo = build_faq_graph(llm=llm, embeddings=InMemoryEmbeddings(), store=almacén)
    return grafo, llm, almacén


# --------------------------------------------------------------------- respond (evidencia)


def test_responde_con_la_evidencia_del_tenant_y_cita_la_fuente() -> None:
    """Con evidencia, el system lleva plantilla + tarea + chunk y la fuente citada."""
    grafo, llm, _ = _grafo(["Abrimos de lunes a sabado de 8:00 a 20:00 (fuente: FAQ Horario)."])
    estado = grafo.invoke(_turno(_PREGUNTA_HORARIO, historial=_historial()))

    assert estado["reply"].startswith("Abrimos de lunes")
    assert len(llm.calls) == 1
    system = llm.calls[0]["system"]
    assert isinstance(system, str)
    assert "Reglas duras" in system
    assert TAREA_RESPONDER in system
    assert "<evidencia>" in system
    assert _HORARIO_A in system
    assert "fuente: FAQ Horario" in system
    assert _HORARIO_B not in system
    assert llm.calls[0]["messages"] == [
        *_historial(),
        LLMMessage(role="user", content=_PREGUNTA_HORARIO),
    ]


def test_prompt_base_completo_llega_al_modelo() -> None:
    """El nodo `respond` monta el system desde la plantilla canónica de `prompts/base`."""
    grafo, llm, _ = _grafo(["respuesta"])
    grafo.invoke(_turno(_PREGUNTA_HORARIO))
    system = llm.calls[0]["system"]
    assert isinstance(system, str)
    assert load_system_prompt() in system


def test_e2e_no_ve_chunks_de_otro_comercio() -> None:
    """Mismo almacén y misma pregunta: cada comercio solo ve sus propios chunks."""
    grafo, llm, _ = _grafo(["A de 8:00", "B de 9:00", "A de 8:00", "B de 9:00"])

    grafo.invoke(_turno(_PREGUNTA_HORARIO, tenant=TENANT))
    system_a = llm.calls[0]["system"]
    assert isinstance(system_a, str)
    assert _HORARIO_A in system_a
    assert _HORARIO_B not in system_a

    grafo.invoke(_turno(_PREGUNTA_HORARIO, tenant=OTRO_TENANT))
    system_b = llm.calls[1]["system"]
    assert isinstance(system_b, str)
    assert _HORARIO_B in system_b
    assert _HORARIO_A not in system_b


# ------------------------------------------------------------------- fallback (sin evidencia)


def test_sin_evidencia_responde_fallback_sin_invocar_al_modelo() -> None:
    """Pregunta fuera del conocimiento: mensaje de dominio y cero llamadas al LLM."""
    grafo, llm, _ = _grafo(["esto no debería usarse"])
    estado = grafo.invoke(_turno(_PREGUNTA_SIN_RESPUESTA))

    assert estado["reply"] == mensaje_fallback("sin_evidencia")
    assert "evidence" not in estado
    assert estado["fallback_reason"] == "sin_evidencia"
    assert llm.calls == []


def test_almacen_caido_degrada_sin_invocar_al_modelo() -> None:
    """Aurora no disponible: mensaje de degradación distinto y sin llamada al LLM."""
    grafo, llm, _ = _grafo(["no debería usarse"], store=_AlmacenCaido())
    estado = grafo.invoke(_turno(_PREGUNTA_HORARIO))

    assert estado["reply"] == mensaje_fallback("almacen_no_disponible")
    assert estado["fallback_reason"] == "almacen_no_disponible"
    assert llm.calls == []


def test_mensajes_de_fallback_son_distintos_y_honestos() -> None:
    """Los dos motivos de degradación tienen mensajes propios (regla 3 del slice)."""
    sin_evidencia = mensaje_fallback("sin_evidencia")
    sin_almacen = mensaje_fallback("almacen_no_disponible")
    assert sin_evidencia != sin_almacen
    assert "No tengo esa información" in sin_evidencia
    assert "No pude consultar" in sin_almacen


# ------------------------------------------------------------------- nodos sueltos y aristas


def test_retrieve_escribe_la_evidencia_recuperada() -> None:
    """El nodo `retrieve` entrega los chunks ya filtrados por la tool."""
    deps = Deps(
        llm=_FakeLLM([]),
        tools=KnowledgeTools(embeddings=InMemoryEmbeddings(), store=_almacen()),
    )
    estado = retrieve(_turno(_PREGUNTA_HORARIO), deps=deps)
    assert len(estado["evidence"]) == 1
    assert estado["evidence"][0].title == "FAQ Horario"
    assert "fallback_reason" not in estado


def test_retrieve_sin_evidencia_escribe_el_motivo() -> None:
    """Sin chunks por encima del umbral, `retrieve` marca el motivo de fallback."""
    deps = Deps(
        llm=_FakeLLM([]),
        tools=KnowledgeTools(embeddings=InMemoryEmbeddings(), store=_almacen()),
    )
    estado = retrieve(_turno(_PREGUNTA_SIN_RESPUESTA), deps=deps)
    assert estado["fallback_reason"] == "sin_evidencia"
    assert "evidence" not in estado


def test_fallback_directo_responde_con_el_mensaje_del_dominio() -> None:
    """El nodo `fallback` no necesita DI: sale todo de `domain.rules`."""
    estado = fallback(_turno("x", historial=[]))
    assert estado["reply"] == mensaje_fallback("sin_evidencia")
    assert "history" in estado


def test_ruta_tras_recuperar_decide_entre_responder_y_fallback() -> None:
    """La arista condicional solo manda a `respond` cuando hay evidencia."""
    con_evidencia = _turno(_PREGUNTA_HORARIO)
    con_evidencia["evidence"] = []
    con_motivo = _turno(_PREGUNTA_HORARIO)
    con_motivo["fallback_reason"] = "sin_evidencia"
    assert ruta_tras_recuperar(con_evidencia) == "respond"
    assert ruta_tras_recuperar(con_motivo) == "fallback"
    assert ruta_tras_recuperar(_turno(_PREGUNTA_HORARIO)) == "respond"


def test_fallback_cubre_los_dos_motivos_del_contrato() -> None:
    """El nodo `fallback` responde a cualquier motivo (y al ausente) sin excepciones."""
    degradado = _turno("x")
    degradado["fallback_reason"] = "almacen_no_disponible"
    assert fallback(degradado)["reply"] == mensaje_fallback("almacen_no_disponible")
    sin_motivo = _turno("x")
    assert fallback(sin_motivo)["reply"] == mensaje_fallback("sin_evidencia")
