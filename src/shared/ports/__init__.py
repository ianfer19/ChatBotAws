"""Ports transversales (Protocol/ABC): LLMPort, ClockPort y EventBusPort."""

from shared.ports.base import ClockPort, EventBusPort, LLMPort

__all__ = ["ClockPort", "EventBusPort", "LLMPort"]
