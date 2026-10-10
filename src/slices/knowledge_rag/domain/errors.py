"""Errores tipados del dominio de conocimiento: los nodos y tools los traducen.

Subclases de `shared.errors.AppError` con `code` estable para logs, métricas y
tests; el mensaje es para el log, nunca se muestra tal cual al usuario final.

`GuardrailBlocked` existe desde aquí porque lo define el contrato funcional del
slice (AGENTS.md), pero solo se lanza desde el Paso 13 (`ApplyGuardrail`,
ADR 0008); hoy es un contrato sin emisor, igual que `LegacyTimeout` en `orders`.
"""

from shared.errors import AppError


class NoEvidenceFound(AppError):
    """Ningún chunk superó el umbral de similitud: no hay evidencia que citar."""

    code = "no_evidence_found"
    http_status = 404


class IngestValidationFailed(AppError):
    """Origen no autorizado o documento inválido: no se indexa (anti-poisoning)."""

    code = "ingest_validation_failed"
    http_status = 422


class VectorStoreUnavailable(AppError):
    """Aurora/pgvector no responde: el turno continúa sin RAG (respuesta degradada)."""

    code = "vector_store_unavailable"
    http_status = 503


class GuardrailBlocked(AppError):
    """El contextual grounding rechazó la respuesta candidata (Paso 13)."""

    code = "guardrail_blocked"
    http_status = 403
