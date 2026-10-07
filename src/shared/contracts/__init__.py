"""Mensajes y eventos que cruzan entre slices; único canal de comunicación entre slices."""

from shared.contracts.messages import (
    CustomerContext,
    InboundMessage,
    OutboundMessage,
    RoutedTurn,
)
from shared.contracts.types import AgentName, Channel, Intent

__all__ = [
    "AgentName",
    "Channel",
    "CustomerContext",
    "InboundMessage",
    "Intent",
    "OutboundMessage",
    "RoutedTurn",
]
