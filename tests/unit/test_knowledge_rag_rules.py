"""Reglas del dominio `knowledge_rag`: chunking, anti-poisoning y evidencia (Paso 7).

Cubren el contrato del slice (AGENTS.md): fallback sin evidencia, umbral aplicado,
allowlist de orígenes y solapamiento del chunking — todo puro, sin AWS.
"""

import pytest

from shared.ports.vector import VectorHit
from slices.knowledge_rag.domain.entities import SourceDocument
from slices.knowledge_rag.domain.errors import IngestValidationFailed, NoEvidenceFound
from slices.knowledge_rag.domain.rules import (
    CHUNK_OVERLAP_CHARS,
    MAX_CHUNK_CHARS,
    SIMILITUDE_THRESHOLD,
    chunk_document,
    compute_content_hash,
    select_evidence,
    validate_document,
)

_TENANT = "Sede_Elite_01"


def _doc(**sobrescribir: object) -> SourceDocument:
    """Documento mínimo válido para los tests del dominio.

    Args:
        sobrescribir: Campos a reemplazar (para probar validación).

    Returns:
        El documento ya validado por Pydantic.
    """
    campos: dict[str, object] = {
        "tenant_id": _TENANT,
        "source_type": "faq",
        "source_id": "faq-1",
        "title": "Horario",
        "content": "Abrimos de lunes a sábado. Los domingos cerramos.",
        "metadata": {"section": "visita"},
    }
    campos.update(sobrescribir)
    return SourceDocument.model_validate(campos)


def _hit(texto: str, score: float, **metadata: str) -> VectorHit:
    """Vecino falso con metadata por defecto de origen permitido.

    Args:
        texto: Texto del chunk.
        score: Similitud 0..1.
        metadata: Overrides del metadata (p. ej. `source_type`).

    Returns:
        El hit validado por el contrato del port vectorial.
    """
    campos: dict[str, object] = {
        "id": f"chunk-{abs(hash(texto)) % 10_000}",
        "tenant_id": _TENANT,
        "text": texto,
        "score": score,
        "metadata": {
            "source_type": "faq",
            "source_id": "faq-1",
            "title": "Horario",
            "section": "visita",
            **metadata,
        },
    }
    return VectorHit.model_validate(campos)


# --- validate_document (anti-poisoning) -------------------------------------


@pytest.mark.parametrize("origen", ["product", "service", "faq", "policy"])
def test_las_fuentes_permitidas_pasan_la_politica(origen: str) -> None:
    """La allowlist de DATA_MODEL admite los cuatro orígenes de conocimiento."""
    validate_document(_doc(source_type=origen))


def test_un_origen_no_permitido_no_se_indexa() -> None:
    """Un origen de contenido de usuario (p. ej. reseñas) se rechaza en la ingesta."""
    with pytest.raises(IngestValidationFailed):
        validate_document(_doc(source_type="review"))
    with pytest.raises(IngestValidationFailed):
        chunk_document(_doc(source_type="review"))


def test_contenido_vacio_tras_el_saneado_no_se_indexa() -> None:
    """Un documento sin texto indexable no genera chunks."""
    with pytest.raises(IngestValidationFailed):
        validate_document(_doc(content="   \n  "))


# --- compute_content_hash -----------------------------------------------------


def test_el_hash_es_estable_y_cambia_con_el_contenido() -> None:
    """Re-ingesta idempotente: mismo contenido = mismo hash; distinto = distinto."""
    assert compute_content_hash("hola") == compute_content_hash("hola")
    assert compute_content_hash("hola") != compute_content_hash("hola ")


# --- chunk_document ------------------------------------------------------------


def test_el_chunking_trocea_por_parrafos_y_ordena_posiciones() -> None:
    """Los párrafos no se mezclan y las posiciones son consecutivas."""
    contenido = "Primer párrafo corto.\n\nSegundo párrafo también corto."
    chunks = chunk_document(_doc(content=contenido))
    assert len(chunks) == 2
    assert [c.position for c in chunks] == [0, 1]
    assert chunks[0].text == "Primer párrafo corto."
    assert chunks[1].text == "Segundo párrafo también corto."
    assert all(c.tenant_id == _TENANT for c in chunks)


def test_las_oraciones_largas_no_superan_el_tamano_maximo() -> None:
    """Ningún fragmento producido por oraciones pasa de `MAX_CHUNK_CHARS`."""
    oraciones = " ".join(f"Esta es la oración número {i} con contenido útil." for i in range(80))
    chunks = chunk_document(_doc(content=oraciones))
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)


def test_los_fragmentos_consecutivos_comparten_contexto() -> None:
    """El solapamiento evita cortar el contexto entre fragmentos consecutivos."""
    oraciones = " ".join(f"Oración informativa número {i} del comercio." for i in range(60))
    chunks = chunk_document(_doc(content=oraciones))
    assert len(chunks) > 1
    cola = chunks[0].text[-40:]
    assert cola in chunks[1].text


def test_una_linea_gigante_se_parte_con_solapamiento_de_caracteres() -> None:
    """Sin signos de puntuación se corta por ventanas con solapamiento exacto."""
    gigante = "x" * (MAX_CHUNK_CHARS * 3)
    chunks = chunk_document(_doc(content=gigante))
    assert len(chunks) >= 3
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
    assert chunks[0].text[-CHUNK_OVERLAP_CHARS:] == chunks[1].text[:CHUNK_OVERLAP_CHARS]


def test_el_chunking_no_pierde_el_tenant_ni_el_origen() -> None:
    """Todo fragmento hereda tenant, origen y fuente del documento (regla 1 y 5)."""
    chunks = chunk_document(_doc())
    assert all(c.tenant_id == _TENANT for c in chunks)
    assert all(c.source_type == "faq" for c in chunks)
    assert all(c.source_id == "faq-1" for c in chunks)


# --- select_evidence -----------------------------------------------------------


def test_el_umbral_descarta_los_candidatos_poco_parecidos() -> None:
    """Solo pasa la evidencia igual o mejor que `SIMILITUDE_THRESHOLD`."""
    hits = [_hit("abrimos de lunes a sábado", 0.92), _hit("tema ajeno", 0.12)]
    evidencia = select_evidence(hits)
    assert [e.text for e in evidencia] == ["abrimos de lunes a sábado"]
    assert SIMILITUDE_THRESHOLD > 0.12


def test_sin_evidencia_sobre_el_umbral_se_lanza_no_evidence_found() -> None:
    """El fallback nunca inventa: sin candidatos buenos no hay evidencia."""
    with pytest.raises(NoEvidenceFound):
        select_evidence([_hit("nada relevante", 0.1)])


def test_sin_hits_tampoco_hay_evidencia() -> None:
    """Una búsqueda vacía (tenant sin conocimiento) cae en el mismo fallback."""
    with pytest.raises(NoEvidenceFound):
        select_evidence([])


def test_los_textos_casi_identicos_se_deduplican() -> None:
    """El mismo fragmento recuperado dos veces cuenta como una sola evidencia."""
    duplicado = "Abrimos de lunes a sábado."
    hits = [_hit(duplicado, 0.9), _hit("  abrimos de lunes a sábado. ", 0.85)]
    evidencia = select_evidence(hits)
    assert len(evidencia) == 1


def test_un_origen_desconocido_en_el_metadata_no_fundamenta() -> None:
    """Anti-poisoning también en la lectura: origen fuera de allowlist = descartado."""
    hits = [
        _hit("contenido confiable", 0.95),
        _hit("reseña envenenada", 0.99, source_type="review"),
    ]
    evidencia = select_evidence(hits)
    assert [e.text for e in evidencia] == ["contenido confiable"]
    with pytest.raises(NoEvidenceFound):
        select_evidence([_hit("solo reseña", 0.99, source_type="review")])


def test_la_evidencia_sale_ordenada_y_acotada_al_top_k() -> None:
    """De mayor a menor score y sin pasar del máximo pedido."""
    hits = [
        _hit("tercera", 0.70),
        _hit("primera", 0.95),
        _hit("segunda", 0.85),
    ]
    evidencia = select_evidence(hits, top_k=2)
    assert [e.text for e in evidencia] == ["primera", "segunda"]


def test_la_evidencia_no_filtros_de_origen_se_van_del_metadata() -> None:
    """El contrato de salida solo conserva el metadata útil para citar."""
    evidencia = select_evidence([_hit("abrimos de lunes", 0.9)])
    assert evidencia[0].source_type == "faq"
    assert evidencia[0].source_id == "faq-1"
    assert evidencia[0].title == "Horario"
    assert "source_type" not in evidencia[0].metadata
    assert evidencia[0].metadata == {"section": "visita"}
