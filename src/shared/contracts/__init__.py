"""Mensajes y eventos que cruzan entre slices; único canal de comunicación entre slices."""

from shared.contracts.messages import (
    CustomerContext,
    InboundMessage,
    OutboundMessage,
    RoutedTurn,
)
from shared.contracts.pending import (
    ACTIVE_STATUSES,
    COMMITIBLE_STATUSES,
    ConfirmationPolicy,
    DraftStatus,
    PendingDraft,
    PolicyDecision,
    compute_payload_hash,
)
from shared.contracts.rag import EvidenceChunk, KnowledgeQuery, SourceType
from shared.contracts.types import AgentName, Channel, Intent

__all__ = [
    "ACTIVE_STATUSES",
    "COMMITIBLE_STATUSES",
    "AgentName",
    "Channel",
    "ConfirmationPolicy",
    "CustomerContext",
    "DraftStatus",
    "EvidenceChunk",
    "InboundMessage",
    "Intent",
    "KnowledgeQuery",
    "OutboundMessage",
    "PendingDraft",
    "PolicyDecision",
    "RoutedTurn",
    "SourceType",
    "compute_payload_hash",
]
