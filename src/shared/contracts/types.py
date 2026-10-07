"""Tipos primitivos compartidos por los contratos entre slices (ADR 0009 y supervisor)."""

from typing import Literal

# Alias clásicos (no `type X = ...`): pydantic 2.9 aún no resuelve los alias PEP 695.
Channel = Literal["whatsapp", "instagram", "messenger"]
# Canal Meta por el que entra o sale un mensaje; el dominio no distingue entre ellos.

Intent = Literal["greeting", "smalltalk", "sales", "appointments", "orders", "faq"]
# Intenciones que clasifica el supervisor; `greeting`/`smalltalk` tienen ruta propia.

AgentName = Literal["supervisor", "sales", "appointments", "orders", "faq"]
# Agente destino de un turno enrutado.
# TODO(decision): nombre final del agente de ventas y del slice que lo aloja.
