"""Caso de uso admin del gateway: alta de canal de un comercio (Fase 5).

El endpoint `POST /admin/channels` permite registrar en dev el mapeo canal→tenant
y sus credenciales en SSM sin tocar AWS a mano (decisión 4 del Paso 9). No decide
nada del negocio del comercio: valida la forma, delega en los ports y responde;
el token propio mínimo del endpoint lo valida el handler (decisión 6).
"""

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.types import Channel
from shared.errors import ValidationError
from shared.logging import get_logger
from slices.conversation_gateway.domain.ports import ChannelMappingWriterPort, CredentialsPort

logger = get_logger(__name__)


class AdminChannelRequest(BaseModel):
    """Cuerpo del `POST /admin/channels` (validado antes de tocar AWS).

    Los secretos son opcionales (el alta puede ser solo del mapeo) pero, si
    vienen, no pueden ser vacíos: un token en blanco es una configuración rota,
    no una credencial ausente.

    Attributes:
        channel: Canal de Meta del emisor.
        emitter_id: Id del emisor (`phone_number_id`, id de página).
        tenant_id: Comercio dueño (`store_id`).
        access_token: Token opcional del canal (SecureString).
        app_secret: Secreto opcional de la app (SecureString).
    """

    model_config = ConfigDict(extra="forbid")

    channel: Channel
    emitter_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    access_token: str | None = Field(default=None, min_length=1)
    app_secret: str | None = Field(default=None, min_length=1)


class AdminChannelsUseCase:
    """Alta idempotente de un canal de comercio: mapeo primero, credenciales después.

    El orden importa: el webhook solo necesita el mapeo para resolver tenant; si
    SSM falla después, reintentar el admin es inocuo (ambas operaciones
    sobrescriben el mismo estado).

    Args:
        mapping: Escritura del mapeo canal→tenant (`DynamoChannelMapping`).
        credentials: Almacenamiento de credenciales (`SsmCredentialStore`).

    Example:
        >>> from slices.conversation_gateway.infrastructure.in_memory import (
        ...     InMemoryCredentialStore,
        ...     InMemoryTenantResolver,
        ... )
        >>> from slices.conversation_gateway.application.admin import AdminChannelsUseCase
        >>> caso = AdminChannelsUseCase(
        ...     mapping=InMemoryTenantResolver(),
        ...     credentials=InMemoryCredentialStore(),
        ... )
        >>> caso.register_channel(
        ...     AdminChannelRequest(
        ...         channel="whatsapp",
        ...         emitter_id="1000",
        ...         tenant_id="Sede_Elite_01",
        ...         access_token="tok",
        ...     )
        ... )
    """

    def __init__(self, *, mapping: ChannelMappingWriterPort, credentials: CredentialsPort) -> None:
        self._mapping = mapping
        self._credentials = credentials

    def register_channel(self, request: AdminChannelRequest) -> None:
        """Registra el emisor hacia el comercio y guarda las credenciales recibidas.

        Args:
            request: Cuerpo ya validado del endpoint admin (`AdminChannelRequest`).

        Returns:
            None; la operación es idempotente y sobrescribe el estado previo.

        Raises:
            ValidationError: Si falta `emitter_id` o `tenant_id` (defensa en capas:
                el modelo ya lo valida, pero la regla vive en la aplicación).
            ToolError/ToolTimeoutError: Si DynamoDB o SSM fallan.
        """
        channel = request.channel
        if not request.emitter_id or not request.tenant_id:
            raise ValidationError("faltan emitter_id o tenant_id en el alta de canal")
        self._mapping.register(
            channel=channel, emitter_id=request.emitter_id, tenant_id=request.tenant_id
        )
        if request.access_token is not None:
            self._credentials.put_access_token(
                channel=channel, tenant_id=request.tenant_id, token=request.access_token
            )
        if request.app_secret is not None:
            self._credentials.put_app_secret(
                channel=channel, tenant_id=request.tenant_id, secret=request.app_secret
            )
        logger.info(
            "admin.canal_registrado",
            extra={"channel": channel, "tenant_id": request.tenant_id},
        )
