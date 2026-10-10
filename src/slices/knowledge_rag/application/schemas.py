"""Modelos Pydantic de la aplicación: la tool y el reporte de ingesta (Paso 7).

Espejo de `orders/application/schemas.py`: los contratos públicos hacia otros
slices viven en `shared/contracts/` (`KnowledgeQuery`, `EvidenceChunk`); nada de
aquí viaja al `domain/`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.rag import EvidenceChunk

__all__ = ["IngestReport", "ToolName", "ToolResult"]

ToolName = Literal["search_knowledge"]
"""Tools que este slice expone al LLM (allowlist; solo lectura)."""


class ToolResult(BaseModel):
    """Salida de `search_knowledge`: la única evidencia con la que se responde.

    Args:
        tool: Tool que produjo el resultado.
        evidence: Chunks recuperados, ya filtrados por umbral y tenant;
            `NoEvidenceFound` (no un resultado vacío) cuando no hay ninguno.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ToolName
    evidence: list[EvidenceChunk] = Field(min_length=1)


class IngestReport(BaseModel):
    """Resultado de una corrida de ingesta, para logs, métricas y tests.

    Args:
        documents: Documentos que entregó la fuente para el tenant.
        ingested: Documentos re-indexados (contenido cambiado).
        skipped: Documentos omitidos por hash idéntico (sin cambios).
        rejected: `source_id` rechazados por la política anti-poisoning.
        chunks: Chunks escritos en el almacén en esta corrida.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: int = Field(ge=0)
    ingested: int = Field(ge=0)
    skipped: int = Field(ge=0)
    rejected: tuple[str, ...] = ()
    chunks: int = Field(ge=0)
