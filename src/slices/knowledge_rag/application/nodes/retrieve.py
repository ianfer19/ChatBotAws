"""Nodo `retrieve`: recupera la evidencia del turno con `search_knowledge`.

Consulta la tool con los ids del estado (contexto resuelto en el gateway, nunca
del payload del LLM). Sin evidencia utilizable o con el almacén caído, el nodo no
rompe el turno: escribe el motivo de degradación y la arista condicional manda a
`fallback` (sin invocar al modelo). Un `ValidationError` (turno mal construido) sí
se propaga: no es una degradación sino un error de composición.
"""

from shared.logging import get_logger
from slices.knowledge_rag.application.deps import Deps
from slices.knowledge_rag.application.state import AgentState
from slices.knowledge_rag.domain.errors import NoEvidenceFound, VectorStoreUnavailable

_logger = get_logger(__name__)


def retrieve(state: AgentState, *, deps: Deps) -> AgentState:
    """Ejecuta `search_knowledge` con el tenant y la pregunta del turno.

    Args:
        state: Turno con `tenant_id`, `correlation_id` y `user_message`.
        deps: Tool `search_knowledge` cableada con embeddings y almacén.

    Returns:
        Estado con `evidence` si hay chunks por encima del umbral; o con
        `fallback_reason` (`sin_evidencia` o `almacen_no_disponible`) si no.

    Raises:
        ValidationError: Si el turno llegó sin tenant, correlation o pregunta
            (error de composición, no se degrada).
    """
    try:
        resultado = deps.tools.search_knowledge(
            tenant_id=state["tenant_id"],
            correlation_id=state["correlation_id"],
            query=state["user_message"],
        )
    except NoEvidenceFound:
        return {**state, "fallback_reason": "sin_evidencia"}
    except VectorStoreUnavailable:
        _logger.error(
            "knowledge_rag.recuperacion_degradada",
            extra={
                "tenant_id": state["tenant_id"],
                "correlation_id": state["correlation_id"],
            },
        )
        return {**state, "fallback_reason": "almacen_no_disponible"}
    return {**state, "evidence": list(resultado.evidence)}
