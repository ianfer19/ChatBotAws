"""Dobles en memoria del gateway: resolución de tenant, dedup y canal (previo a la infraestructura).

Mismo papel que `orders/infrastructure/in_memory.py`: probar el flujo del webhook sin
DynamoDB, SSM, SQS ni llamadas reales a Meta (ROADMAP §2.4). El aislamiento por tenant
vive en la clave del doble, nunca en el payload.
"""

from collections.abc import Mapping, Sequence

from shared.contracts.messages import OutboundMessage
from shared.contracts.types import Channel
from shared.errors import TenantNotFoundError, ValidationError
from shared.ports import ChannelMessage


class InMemoryTenantResolver:
    """`TenantResolverPort` con un mapeo fijo `(canal, emisor) → tenant`.

    Example:
        >>> from slices.conversation_gateway.infrastructure.in_memory import InMemoryTenantResolver
        >>> resolver = InMemoryTenantResolver({("whatsapp", "1000"): "Sede_Elite_01"})
        >>> resolver.resolve(channel="whatsapp", emitter_id="1000")
        'Sede_Elite_01'
    """

    def __init__(self, mapping: Mapping[tuple[Channel, str], str] | None = None) -> None:
        """Copia el mapeo de prueba en un diccionario propio.

        Args:
            mapping: Pares `(channel, emitter_id) → tenant_id`; vacío = nadie resuelto.
        """
        self._mapping = dict(mapping or {})

    def resolve(self, *, channel: Channel, emitter_id: str) -> str:
        """Devuelve el tenant del emisor o levanta `TenantNotFoundError`.

        Args:
            channel: Canal del webhook.
            emitter_id: Id del emisor Meta.

        Returns:
            El `tenant_id` registrado para ese par.

        Raises:
            TenantNotFoundError: Si no hay mapeo o falta `emitter_id`.
        """
        if not emitter_id:
            raise ValidationError("emitter_id vacío en el resolutor de tenant")
        clave = (channel, emitter_id)
        if clave not in self._mapping:
            raise TenantNotFoundError(
                "sin mapeo de canal→tenant",
                details={"channel": channel},
            )
        return self._mapping[clave]


class InMemoryDeduplication:
    """`DeduplicationPort` sobre un conjunto (ignora el TTL por no llevar reloj).

    Example:
        >>> from slices.conversation_gateway.infrastructure.in_memory import InMemoryDeduplication
        >>> dedup = InMemoryDeduplication()
        >>> dedup.register_once(tenant_id="Sede_Elite_01", message_id="wamid.1")
        True
        >>> dedup.register_once(tenant_id="Sede_Elite_01", message_id="wamid.1")
        False
    """

    def __init__(self) -> None:
        """Guarda los `(tenant_id, message_id)` ya vistos en este proceso."""
        self._vistos: set[tuple[str, str]] = set()

    def register_once(self, *, tenant_id: str, message_id: str) -> bool:
        """Registra el mensaje; `False` si ese tenant ya lo había registrado.

        Args:
            tenant_id: Comercio resuelto.
            message_id: Id del mensaje en el canal.

        Returns:
            `True` si es nuevo; `False` si es un duplicado.

        Raises:
            ValidationError: Si falta `tenant_id` o `message_id`.
        """
        if not tenant_id or not message_id:
            raise ValidationError("faltan tenant_id o message_id en la deduplicación")
        clave = (tenant_id, message_id)
        if clave in self._vistos:
            return False
        self._vistos.add(clave)
        return True


class InMemoryChannel:
    """`ChannelPort` de tests: captura lo enviado y devuelve la lista fija de mensajes.

    No interpreta payloads reales (eso lo hacen los adaptadores de la Fase 3): el
    constructor recibe de antemano los `ChannelMessage` que el doble devolverá.

    Example:
        >>> from datetime import UTC, datetime
        >>> from slices.conversation_gateway.infrastructure.in_memory import InMemoryChannel
        >>> canal = InMemoryChannel()
        >>> canal.verify_credentials(channel="whatsapp", tenant_id="Sede_Elite_01")
        True
    """

    def __init__(
        self,
        *,
        normalized: Sequence[ChannelMessage] = (),
        credentials_ok: bool = True,
    ) -> None:
        """Prepara el doble con los mensajes fijos y el estado de credenciales.

        Args:
            normalized: Mensajes que devolverá `normalize_inbound` (vacío = evento
                a ignorar, como una lista sin mensajes).
            credentials_ok: Resultado de `verify_credentials`.
        """
        self.sent: list[OutboundMessage] = []
        self._normalized = list(normalized)
        self._credentials_ok = credentials_ok

    def normalize_inbound(
        self, payload: Mapping[str, object], *, channel: Channel
    ) -> list[ChannelMessage]:
        """Devuelve los mensajes fijados en el constructor (ignora el payload).

        Args:
            payload: Payload crudo (ignorado por el doble).
            channel: Canal detectado (ignorado por el doble).

        Returns:
            Los `ChannelMessage` configurados (lista vacía si no los hay).
        """
        del payload, channel
        return list(self._normalized)

    def send(self, message: OutboundMessage) -> None:
        """Acumula la respuesta en `sent` en lugar de llamar a Meta.

        Args:
            message: Respuesta saliente a capturar.
        """
        self.sent.append(message)

    def verify_credentials(self, *, channel: Channel, tenant_id: str) -> bool:
        """Devuelve el estado de credenciales fijado en el constructor.

        Args:
            channel: Canal consultado (ignorado por el doble).
            tenant_id: Comercio consultado (ignorado por el doble).

        Returns:
            `True`/`False` según `credentials_ok`.
        """
        del channel, tenant_id
        return self._credentials_ok
