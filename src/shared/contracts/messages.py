"""Mensajes que cruzan entre slices: gateway → supervisor → agentes y contexto cliente.

Son contratos **versionados** (`schema_version`): añadir un campo con valor por defecto
es compatible; romper uno exige migrar a todos los emisores/receptores en el mismo PR.
Los modelos son inmutables (`frozen`) y prohíben campos extra: lo que no pasa el
contrato no se encola ni se ejecuta.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.types import AgentName, Channel, Intent

_MAX_TEXT = 4096  # threat model §8: mensajes más largos se descartan en el gateway


class _ContractBase(BaseModel):
    """Base común de los contratos: inmutables y sin campos extra."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class InboundMessage(_ContractBase):
    """Mensaje normalizado del canal hacia el pipeline (salida del `conversation_gateway`).

    `tenant_id` y `correlation_id` ya están resueltos: el resto del sistema jamás los
    deriva del payload (MULTI_TENANCY §5).
    """

    schema_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=64)
    channel: Channel
    customer_id: str = Field(min_length=1, max_length=64)
    message_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    text: str | None = Field(default=None, max_length=_MAX_TEXT)


class OutboundMessage(_ContractBase):
    """Respuesta del pipeline hacia el canal (entrada al `ChannelPort` de salida)."""

    schema_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=64)
    channel: Channel
    customer_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=_MAX_TEXT)


class RoutedTurn(_ContractBase):
    """Turno clasificado por el `supervisor` y enrutado a un agente destino.

    Contrato de salida del supervisor: siempre conserva el mensaje original con su
    `tenant_id` y `correlation_id` (test de contrato obligatorio).
    """

    schema_version: Literal[1] = 1
    message: InboundMessage
    intent: Intent
    target: AgentName


class CustomerContext(_ContractBase):
    """Contexto del cliente que devuelve la tool `get_customer_context` (lectura).

    Solo identificación y preferencias: **nunca** verdad operacional (precios, stock,
    pedidos ni horas; eso viene del legacy/dominio).
    """

    schema_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    preferences: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    last_seen_at: datetime | None = None
