"""Ports de salida del dominio del gateway (Protocol): la implementación va en infrastructure/.

Mismo criterio que en los demás slices: el dominio declara QUÉ necesita (normalizar el
payload, resolver el tenant del canal, deduplicar mensajes), sin saber si debajo hay
DynamoDB, SQS o dobles en memoria, y siempre con el filtro por comercio explícito en
la firma.
"""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from shared.contracts.types import Channel
from shared.ports import ChannelMessage


@runtime_checkable
class NormalizerPort(Protocol):
    """Normalización del payload crudo a `ChannelMessage` (entrada del pipeline).

    Es la vista de entrada de `shared.ports.ChannelPort`: el `WebhookReceiver` solo
    interpreta el payload (el envío y las credenciales son del consumer, Fases 5-6),
    así que depende de esta interfaz mínima y el adaptador puede crecer hasta cumplir
    `ChannelPort` completo sin tocar la aplicación.
    """

    def normalize_inbound(
        self, payload: Mapping[str, object], *, channel: Channel
    ) -> list[ChannelMessage]:
        """Interpreta el payload de **su** canal y lo normaliza a `ChannelMessage`.

        Args:
            payload: JSON ya parseado del webhook (cuerpo exacto de Meta).
            channel: Canal detectado en el envelope (`detect_channel`).

        Returns:
            Los mensajes normalizados en orden; vacía si el evento se ignora
            (estados de lectura, ecos o reacciones: se acusa 200 sin reprocesar).

        Raises:
            ValidationError: Si el payload no es del formato esperado del canal.
        """
        ...


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

    def release(self, *, tenant_id: str, message_id: str) -> None:
        """Elimina el registro de deduplicación (rollback del encolado fallido).

        El flujo registra ANTES de encolar (si no, un duplicado de Meta procesaría
        dos veces), pero si el encolado falla el registro quedaría huérfano y el
        reintento de Meta lo vería como duplicado, **perdiendo el mensaje**. Por eso
        el webhook libera la clave y re-lanza el error: la idempotencia nunca puede
        convertir un fallo transitorio en pérdida de datos.

        Args:
            tenant_id: Comercio resuelto en el gateway.
            message_id: Id del mensaje en el canal (wamid/mid).

        Returns:
            None; la operación es idempotente (borrar algo ya borrado no falla).

        Raises:
            ValidationError: Si falta `tenant_id` o `message_id`.
            ToolError: Si DynamoDB rechaza el borrado (lo registra el webhook y el
                error original sigue siendo el motivo de la respuesta).
        """
        ...
