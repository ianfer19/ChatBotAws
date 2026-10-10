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


class QueuedMessage(InboundMessage):
    """Mensaje del gateway ya encolado hacia el consumer (SQS, Paso 9).

    Extiende `InboundMessage` con lo que solo necesitan la cola y la persistencia
    de la tabla de mensajes (estructura replicada del legacy, decisión del Paso 9):
    la clase del mensaje, el nombre del remitente, los atributos de media (solo
    atributos; la descarga es `media_handling`, ROADMAP §4) y el payload crudo del
    webhook. El consumer la entrega al supervisor como `InboundMessage` (subclase
    compatible) y guarda el resto en la tabla de mensajes.

    `message_type` es `str` y no el `MessageType` de `shared.ports.channel` para no
    crear un ciclo `contracts ↔ ports` (`ports.channel` ya importa `contracts`).
    """

    message_type: str = Field(default="unknown", max_length=32)
    sender_name: str | None = Field(default=None, max_length=120)
    media_id: str | None = Field(default=None, max_length=128)
    media_type: str | None = Field(default=None, max_length=32)
    media_url: str | None = Field(default=None, max_length=1024)
    # Cuerpo exacto que firmó Meta (bytes ya validados por el webhook). El límite
    # deja margen para el resto del cuerpo del mensaje SQS (256 KiB).
    raw_payload: str = Field(min_length=1, max_length=200_000)


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
