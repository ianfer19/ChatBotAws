"""Ports de salida del dominio del gateway (Protocol): la implementación va en infrastructure/.

Mismo criterio que en los demás slices: el dominio declara QUÉ necesita (resolver el
tenant del canal, deduplicar mensajes), sin saber si debajo hay DynamoDB, SSM o
dobles en memoria, y siempre con el filtro por comercio explícito en la firma.
"""

from typing import Protocol, runtime_checkable

from shared.contracts.types import Channel


@runtime_checkable
class TenantResolverPort(Protocol):
    """Resolución canal→tenant replicada del legacy (`WA_CONFIG#`/`IG_CONFIG#`/`FB_CONFIG#`)."""

    def resolve(self, *, channel: Channel, emitter_id: str) -> str:
        """Devuelve el `store_id` (tenant) dueño de ese emisor Meta.

        Args:
            channel: Canal por el que llegó el webhook.
            emitter_id: Id del emisor del payload (`phone_number_id` en WhatsApp;
                id de página/IG en Messenger/Instagram).

        Returns:
            El `tenant_id` (store_id legado) resuelto.

        Raises:
            TenantNotFoundError: Si no hay mapeo: el usuario recibe «comercio no
                disponible» y jamás se invoca al supervisor (regla 2 del slice).
            ValidationError: Si falta `emitter_id`.
        """
        ...


@runtime_checkable
class DeduplicationPort(Protocol):
    """Idempotencia por `message_id`: Meta reenvía webhooks y no hay que reprocesarlos."""

    def register_once(self, *, tenant_id: str, message_id: str) -> bool:
        """Registra el mensaje como procesado; `False` si ya estaba registrado.

        A diferencia del legacy (`MSG_PROCESSED#<message_id>|DEDUP` global), la clave
        se compone con `tenant_id`: ningún dato cruza comercios, ni siquiera la
        idempotencia.

        Args:
            tenant_id: Comercio resuelto en el gateway.
            message_id: Id del mensaje en el canal (wamid/mid).

        Returns:
            `True` si es la primera vez (mensaje nuevo); `False` si es un duplicado
            (el handler responde 200 silencioso con `DuplicateMessageError`).

        Raises:
            ValidationError: Si falta `tenant_id` o `message_id`.
        """
        ...
