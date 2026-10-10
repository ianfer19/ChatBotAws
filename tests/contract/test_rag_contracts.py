"""Contrato de conocimiento: `KnowledgeQuery` y `EvidenceChunk` (Paso 7, Fase 1).

Frontera compartida entre `knowledge_rag` y sus consumidores (especialista `faq`,
futuras tools): lo que se verifica aquí no puede romperse sin avisar (AGENTS.md
raíz, §9). En particular, **la consulta no admite `tenant_id`** (se inyecta del
contexto, MULTI_TENANCY §5) y la evidencia solo admite orígenes de la allowlist.
"""

import pytest
from pydantic import ValidationError as SchemaValidationError

from shared.contracts import EvidenceChunk, KnowledgeQuery

pytestmark = pytest.mark.contract


def _evidence(**sobrescribir: object) -> EvidenceChunk:
    """Evidencia mínima válida para los tests de contrato.

    Args:
        sobrescribir: Campos a reemplazar (para probar validación).

    Returns:
        El chunk ya validado.
    """
    campos: dict[str, object] = {
        "chunk_id": "chk-1",
        "text": "Abrimos de lunes a sábado.",
        "score": 0.91,
        "source_type": "faq",
        "source_id": "faq-1",
        "title": "Horario",
    }
    campos.update(sobrescribir)
    return EvidenceChunk.model_validate(campos)


def test_knowledge_query_es_inmutable_sin_tenant_ni_claves_ajenas() -> None:
    """La consulta no cambia en caliente y no admite tenant ni claves de más."""
    consulta = KnowledgeQuery(query="¿A qué hora abren?")
    with pytest.raises(SchemaValidationError):
        consulta.query = "otra"  # pyrefly: ignore[read-only]
    with pytest.raises(SchemaValidationError):
        KnowledgeQuery.model_validate({"query": "¿A qué hora abren?", "tenant_id": "Sede_Elite_01"})
    with pytest.raises(SchemaValidationError):
        KnowledgeQuery.model_validate({"query": "¿A qué hora abren?", "source_type": "review"})
    assert "tenant_id" not in KnowledgeQuery.model_fields


def test_knowledge_query_valida_texto_y_top_k() -> None:
    """El texto no puede ser vacío y el top_k tiene límites seguros."""
    with pytest.raises(SchemaValidationError):
        KnowledgeQuery(query="")
    with pytest.raises(SchemaValidationError):
        KnowledgeQuery.model_validate({"query": "x", "top_k": 0})
    with pytest.raises(SchemaValidationError):
        KnowledgeQuery.model_validate({"query": "x", "top_k": 999})


def test_evidence_chunk_es_inmutable_y_sin_tenant() -> None:
    """La evidencia no admite cambios laterales ni un tenant en su payload."""
    chunk = _evidence()
    with pytest.raises(SchemaValidationError):
        chunk.score = 1.0  # pyrefly: ignore[read-only]
    with pytest.raises(SchemaValidationError):
        EvidenceChunk.model_validate({**_evidence().model_dump(), "tenant_id": "Ajeno"})
    assert "tenant_id" not in EvidenceChunk.model_fields


def test_evidence_chunk_valida_score_y_origen() -> None:
    """Score en 0..1 y solo orígenes de la allowlist (anti-poisoning)."""
    with pytest.raises(SchemaValidationError):
        _evidence(score=1.5)
    with pytest.raises(SchemaValidationError):
        _evidence(score=-0.1)
    with pytest.raises(SchemaValidationError):
        _evidence(source_type="review")


def test_los_contratos_sobreviven_un_round_trip() -> None:
    """Lo que se serializa entre slices es exactamente lo que se recibe."""
    consulta = KnowledgeQuery(query="¿Tienen mesas para 6?", top_k=6)
    assert KnowledgeQuery.model_validate(consulta.model_dump()) == consulta
    chunk = _evidence()
    assert EvidenceChunk.model_validate(chunk.model_dump()) == chunk
    assert consulta.schema_version == 1
    assert chunk.schema_version == 1
