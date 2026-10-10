"""`ChannelPort`: única frontera hacia los canales Meta (ADR 0009).

El dominio y la aplicación no saben si el mensaje viene de WhatsApp, Instagram o
Messenger: el adaptador de cada canal (`conversation_gateway/infrastructure/channels/`)
interpreta el payload (`normalize_inbound`), envía la respuesta (`send`) y comprueba
que el comercio tenga credenciales (`verify_credentials`). La clasificación de tipo de
mensaje del ADR 0009 se materializa en el campo `message_type` del resultado.

`ChannelMessage` vive aquí (y no en `contracts/`) porque es el tipo que devuelve este
port, con el mismo criterio que `LLMMessage` en `shared/ports/llm.py`.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.messages import OutboundMessage
from shared.contracts.types import Channel

_MAX_TEXT = 4096  # threat model §8: mensajes más largos se descartan en el gateway

MessageType = Literal[
    "text",
    "image",
    "audio",
    "video",
    "document",
    "location",
    "sticker",
    "unknown",
]
# Tipo de mensaje soportado por los 3 canales; añadir uno es añadir un literal aquí
# y tratarlo en los adaptadores (ADR 0005: romper el contrato exige migrar juntos).


class ChannelMessage(BaseModel):
    """Mensaje de un canal Meta normalizado **antes** de resolver tenant y correlación.

    Contrato puente: lo produce `ChannelPort.normalize_inbound` y lo consume la
    aplicación del gateway para resolver el tenant (por `emitter_id`) y deduplicar
    (por `message_id`) antes de construir el `InboundMessage` definitivo. Es
    inmutable y prohíbe campos extra: lo que no pasa el contrato no se procesa.

    Attributes:
        channel: Canal de origen (whatsapp/instagram/messenger).
        emitter_id: Id del emisor Meta del webhook (`phone_number_id` en WhatsApp;
            id de página/IG en Messenger/Instagram) — la clave del mapeo al tenant.
        customer_id: Remitente (id de WhatsApp o PSID).
        message_id: Id único del mensaje (wamid/mid) — clave de idempotencia.
        timestamp: Marca temporal del mensaje en UTC.
        message_type: Tipo ya clasificado (ver `MessageType`).
        text: Contenido de texto si lo hay (máx. 4096).
        media_id: Id del medio en Meta (solo atributos; la descarga es
            `media_handling`, ROADMAP §4).
        media_type: MIME o clase del medio (image/audio/video/document).
        media_url: URL directa del medio si el canal la aporta (Messenger/Instagram).
        sender_name: Nombre del remitente si el canal lo trae en el payload
            (perfil de WhatsApp); `None` si hay que pedirlo a la Graph API.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    channel: Channel
    emitter_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    message_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    message_type: MessageType = "unknown"
    text: str | None = Field(default=None, max_length=_MAX_TEXT)
    media_id: str | None = Field(default=None, max_length=128)
    media_type: str | None = Field(default=None, max_length=32)
    media_url: str | None = Field(default=None, max_length=1024)
    sender_name: str | None = Field(default=None, max_length=120)


@runtime_checkable
class ChannelPort(Protocol):
    """Operaciones mínimas del dominio sobre un canal Meta (ADR 0009)."""

    def normalize_inbound(
        self, payload: Mapping[str, object], *, channel: Channel
    ) -> list[ChannelMessage]:
        """Interpreta el payload de **su** canal y lo normaliza a `ChannelMessage`.

        Meta puede agrupar varios mensajes en un solo webhook (y el legacy V2 los
        recorre todos), así que el resultado es siempre una lista.

        Args:
            payload: JSON ya parseado del webhook (cuerpo exacto de Meta).
            channel: Canal detectado en el envelope (`detect_channel`).

        Returns:
            Los mensajes normalizados en orden; lista vacía si el evento se ignora
            (estados de lectura, ecos, reacciones: el handler responde 200 sin
            reprocesar).

        Raises:
            ValidationError: Si el payload no es del formato esperado del canal.
        """
        ...

    def send(self, message: OutboundMessage) -> None:
        """Envía la respuesta al cliente en el canal indicado por el mensaje.

        Args:
            message: Respuesta ya redactada, con tenant/correlación resueltos.

        Raises:
            ToolTimeoutError: Si Meta no responde dentro del timeout (retry acotado).
            ToolError: Si Meta devuelve un error (5xx, token inválido).
        """
        ...

    def verify_credentials(self, *, channel: Channel, tenant_id: str) -> bool:
        """Comprueba que el comercio tiene credenciales usables para ese canal.

        Args:
            channel: Canal cuyas credenciales se verifican.
            tenant_id: Comercio dueño de las credenciales (SSM, nunca en el repo).

        Returns:
            `True` si existen y son consistentes; `False` si faltan.
        """
        ...
