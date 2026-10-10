"""Reglas puras de ingesta y recuperación del conocimiento (Paso 7).

Todo aquí es función pura sobre entidades del propio slice: chunking, hash de
idempotencia, anti-poisoning (allowlist de orígenes) y selección de evidencia
con umbral de similitud y deduplicación. Sin I/O, sin AWS, sin LLM.
"""

import hashlib
import re
from collections.abc import Sequence
from typing import cast

from shared.contracts.rag import EvidenceChunk, SourceType
from shared.ports.vector import VectorHit

from .entities import ContentChunk, SourceDocument
from .errors import IngestValidationFailed, NoEvidenceFound

MAX_CHUNK_CHARS: int = 1200
"""Tamaño máximo de un chunk en caracteres (`TODO(verify)`: calibrar con evals)."""

CHUNK_OVERLAP_CHARS: int = 150
"""Solapamiento entre fragmentos consecutivos (`TODO(verify)`, ver RAG.md)."""

SIMILITUDE_THRESHOLD: float = 0.35
"""Umbral mínimo de similitud para aceptar evidencia (`TODO(verify)`: evals)."""

DEFAULT_TOP_K: int = 5
"""Candidatos por defecto antes del umbral (top_k de `KnowledgeQuery`)."""

ALLOWED_SOURCE_TYPES: frozenset[str] = frozenset({"product", "service", "faq", "policy"})
"""Allowlist de orígenes indexables (anti-poisoning): nada fuera de esta lista."""

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def validate_document(document: SourceDocument) -> None:
    """Aplica la política anti-poisoning antes de indexar un documento.

    El `source_type` llega crudo de la fuente externa y debe pertenecer a la
    allowlist; el contenido no puede quedarse vacío tras quitar espacios.

    Args:
        document: Documento crudo devuelto por `KnowledgeSourcePort`.

    Raises:
        IngestValidationFailed: Si el origen no está permitido o el contenido
            no tiene texto indexable.
    """
    if document.source_type not in ALLOWED_SOURCE_TYPES:
        raise IngestValidationFailed(f"source_type no permitido: {document.source_type!r}")
    if not document.content.strip():
        raise IngestValidationFailed("contenido vacío tras saneado")


def compute_content_hash(content: str) -> str:
    """Hash estable del contenido para la re-ingesta idempotente.

    Args:
        content: Texto original del documento.

    Returns:
        SHA-256 en hexadecimal; el mismo contenido produce siempre el mismo hash
        (un documento sin cambios no genera chunks nuevos, RAG.md).
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def chunk_document(document: SourceDocument) -> list[ContentChunk]:
    """Trocea un documento en fragmentos de a lo más `MAX_CHUNK_CHARS`.

    Estrategia por párrafo y por oración con solapamiento (RAG.md): los párrafos
    no se mezclan entre sí; un párrafo mayor que el máximo se parte por oraciones
    con `CHUNK_OVERLAP_CHARS` de cola, y una oración gigante se parte por
    caracteres. Siempre valida el documento antes de trocearlo.

    Args:
        document: Documento crudo de la fuente.

    Returns:
        Fragmentos en orden de posición; vacío nunca (el contenido se validó).

    Raises:
        IngestValidationFailed: Si el documento no pasa la política de ingesta.
    """
    validate_document(document)
    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(document.content) if p.strip()]
    texts: list[str] = []
    for paragraph in paragraphs:
        texts.extend(_split_paragraph(paragraph))
    return [
        ContentChunk(
            tenant_id=document.tenant_id,
            source_type=document.source_type,
            source_id=document.source_id,
            title=document.title,
            text=text,
            position=position,
            metadata=document.metadata,
        )
        for position, text in enumerate(texts)
        if text.strip()
    ]


def select_evidence(
    hits: Sequence[VectorHit],
    *,
    threshold: float = SIMILITUDE_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
) -> list[EvidenceChunk]:
    """Convierte los vecinos recuperados en evidencia utilizable por el agente.

    Aplica tres filtros en defensa del grounding: umbral de similitud,
    deduplicación por texto (casi idénticos) y allowlist de origen leída del
    metadata (un chunk con origen desconocido jamás fundamenta una respuesta).
    Los hits llegan del almacén **ya filtrados por tenant** (regla 1 del slice);
    esta función no admite ni pide un tenant: no hay forma de cruzar comercios.

    Args:
        hits: Vecinos devueltos por `VectorStorePort.search`.
        threshold: Similitud mínima para aceptar un candidato.
        top_k: Máximo de evidencias a devolver (de mayor a menor score).

    Returns:
        Evidencias ordenadas por score descendente, sin duplicados.

    Raises:
        NoEvidenceFound: Si ningún candidato supera el umbral o todos tienen
            origen no permitido (la respuesta pasa al fallback, nunca se inventa).
    """
    evidence: list[EvidenceChunk] = []
    seen: set[str] = set()
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        if hit.score < threshold:
            continue
        dedup_key = " ".join(hit.text.lower().split())
        if not dedup_key or dedup_key in seen:
            continue
        chunk = _to_evidence(hit)
        if chunk is None:
            continue
        seen.add(dedup_key)
        evidence.append(chunk)
        if len(evidence) >= top_k:
            break
    if not evidence:
        raise NoEvidenceFound(f"ningún chunk superó el umbral de similitud {threshold:.2f}")
    return evidence


def _to_evidence(hit: VectorHit) -> EvidenceChunk | None:
    """Mapea un hit del almacén a `EvidenceChunk` si su metadata es de fiar.

    Args:
        hit: Vecino devuelto por la búsqueda vectorial.

    Returns:
        La evidencia lista para el grounding, o `None` si el metadata no trae
        un `source_type` de la allowlist (origen desconocido: no se cita).
    """
    raw_source_type = hit.metadata.get("source_type", "")
    if raw_source_type not in ALLOWED_SOURCE_TYPES:
        return None
    return EvidenceChunk(
        chunk_id=hit.id,
        text=hit.text,
        score=hit.score,
        source_type=cast(SourceType, raw_source_type),
        source_id=hit.metadata.get("source_id", hit.id),
        title=hit.metadata.get("title"),
        metadata={
            key: value
            for key, value in hit.metadata.items()
            if key not in {"source_type", "source_id", "title"}
        },
    )


def _split_paragraph(paragraph: str) -> list[str]:
    """Trocea un párrafo respetando `MAX_CHUNK_CHARS`.

    Args:
        paragraph: Párrafo no vacío.

    Returns:
        Fragmentos del párrafo; uno si ya cabe entero.
    """
    if len(paragraph) <= MAX_CHUNK_CHARS:
        return [paragraph]
    sentences = [s.strip() for s in _SENTENCE_RE.split(paragraph) if s.strip()]
    if len(sentences) <= 1:
        return _hard_split(paragraph)
    return _pack_sentences(sentences)


def _pack_sentences(sentences: list[str]) -> list[str]:
    """Agrupa oraciones en fragmentos con solapamiento de cola.

    Args:
        sentences: Oraciones del párrafo, en orden.

    Returns:
        Fragmentos de a lo más `MAX_CHUNK_CHARS`; el siguiente arranca con la
        cola del anterior (`CHUNK_OVERLAP_CHARS`) para no cortar contexto.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence_len = len(sentence) + 1
        while current and current_len + sentence_len > MAX_CHUNK_CHARS:
            chunks.append(" ".join(current))
            tail: list[str] = _tail_overlap(current)
            if len(tail) >= len(current):
                tail = []  # sin progreso posible: el siguiente arranca limpio
            current = tail
            current_len = sum(len(part) + 1 for part in current)
        if not current and sentence_len > MAX_CHUNK_CHARS:
            parts = _hard_split(sentence)
            chunks.extend(parts[:-1])
            current = [parts[-1]]
            current_len = len(parts[-1])
            continue
        current.append(sentence)
        current_len += sentence_len
    if current:
        chunks.append(" ".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def _tail_overlap(current: list[str]) -> list[str]:
    """Últimas oraciones del fragmento anterior hasta `CHUNK_OVERLAP_CHARS`.

    Args:
        current: Fragmento que se acaba de cerrar, en orden.

    Returns:
        Cola (en orden) que arranca el siguiente fragmento; vacía si ni una
        oración entera cabe en el solapamiento.
    """
    tail: list[str] = []
    size = 0
    for sentence in reversed(current):
        sentence_len = len(sentence) + 1
        if size + sentence_len > CHUNK_OVERLAP_CHARS:
            break
        tail.append(sentence)
        size += sentence_len
    tail.reverse()
    return tail


def _hard_split(text: str) -> list[str]:
    """Corta por caracteres con solapamiento (oraciones o párrafos gigantes).

    Args:
        text: Texto más grande que `MAX_CHUNK_CHARS`.

    Returns:
        Ventanas de a lo más `MAX_CHUNK_CHARS` con `CHUNK_OVERLAP_CHARS` de
        solapamiento entre consecutivas.
    """
    step = max(MAX_CHUNK_CHARS - CHUNK_OVERLAP_CHARS, 1)
    return [
        text[start : start + MAX_CHUNK_CHARS]
        for start in range(0, len(text), step)
        if text[start : start + MAX_CHUNK_CHARS].strip()
    ]
