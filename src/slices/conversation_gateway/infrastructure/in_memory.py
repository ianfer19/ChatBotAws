"""Dobles en memoria del gateway: tenant, dedup, credenciales, canal y bus.

Mismo papel que `orders/infrastructure/in_memory.py`: probar el flujo del webhook sin
DynamoDB, SSM, SQS ni llamadas reales a Meta (ROADMAP §2.4). El aislamiento por tenant
vive en la clave del doble, nunca en el payload.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from requests import Response

from shared.contracts.messages import OutboundMessage
from shared.contracts.types import Channel
from shared.errors import TenantNotFoundError, ValidationError
from shared.ports import ChannelMessage
from slices.conversation_gateway.domain.errors import CredentialNotFoundError


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

    def register(self, *, channel: Channel, emitter_id: str, tenant_id: str) -> None:
        """Añade (o sobrescribe) el mapeo del emisor hacia ese comercio.

        Args:
            channel: Canal de Meta del emisor.
            emitter_id: Id del emisor Meta.
            tenant_id: Comercio dueño.

        Returns:
            None; idempotente como el ítem real de DynamoDB.

        Raises:
            ValidationError: Si falta cualquiera de los tres valores.
        """
        if not channel or not emitter_id or not tenant_id:
            raise ValidationError("faltan channel, emitter_id o tenant_id en el mapeo")
        self._mapping[(channel, emitter_id)] = tenant_id


class InMemoryCredentialStore:
    """`CredentialsPort` con un diccionario en memoria (nunca valores reales).

    Example:
        >>> from slices.conversation_gateway.infrastructure.in_memory import InMemoryCredentialStore
        >>> store = InMemoryCredentialStore()
        >>> store.put_access_token(channel="whatsapp", tenant_id="Sede_Elite_01", token="tok")
        >>> store.get_access_token(channel="whatsapp", tenant_id="Sede_Elite_01")
        'tok'
    """

    def __init__(self) -> None:
        """Guarda los secretos como `(canal, tenant, nombre) → valor`."""
        self._secretos: dict[tuple[Channel, str, str], str] = {}

    def get_access_token(self, *, channel: Channel, tenant_id: str) -> str:
        """Devuelve el access token guardado (o `CredentialNotFoundError`).

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.

        Returns:
            El token registrado por el doble.

        Raises:
            CredentialNotFoundError: Si no hay token para ese par.
            ValidationError: Si falta `tenant_id`.
        """
        return self._leer(channel=channel, tenant_id=tenant_id, nombre="access_token")

    def put_access_token(self, *, channel: Channel, tenant_id: str, token: str) -> None:
        """Registra el access token en el diccionario.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            token: Valor del token.

        Returns:
            None.

        Raises:
            ValidationError: Si falta `tenant_id` o `token`.
        """
        self._escribir(channel=channel, tenant_id=tenant_id, nombre="access_token", valor=token)

    def put_app_secret(self, *, channel: Channel, tenant_id: str, secret: str) -> None:
        """Registra el app secret en el diccionario.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            secret: Valor del secreto.

        Returns:
            None.

        Raises:
            ValidationError: Si falta `tenant_id` o `secret`.
        """
        self._escribir(channel=channel, tenant_id=tenant_id, nombre="app_secret", valor=secret)

    def _leer(self, *, channel: Channel, tenant_id: str, nombre: str) -> str:
        """Busca un valor secreto por la clave compuesta.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            nombre: `access_token` o `app_secret`.

        Returns:
            El valor registrado.

        Raises:
            CredentialNotFoundError: Si no existe esa clave.
            ValidationError: Si falta `tenant_id`.
        """
        if not tenant_id:
            raise ValidationError("tenant_id vacio en el doble de credenciales")
        clave = (channel, tenant_id, nombre)
        if clave not in self._secretos:
            raise CredentialNotFoundError(
                "credencial ausente en el doble",
                details={"channel": channel, "tenant_id": tenant_id, "parametro": nombre},
            )
        return self._secretos[clave]

    def _escribir(self, *, channel: Channel, tenant_id: str, nombre: str, valor: str) -> None:
        """Registra un valor secreto por la clave compuesta.

        Args:
            channel: Canal de Meta.
            tenant_id: Comercio dueño.
            nombre: `access_token` o `app_secret`.
            valor: Valor del secreto.

        Returns:
            None.

        Raises:
            ValidationError: Si falta `tenant_id` o el valor.
        """
        if not tenant_id or not valor:
            raise ValidationError("faltan tenant_id o valor en el doble de credenciales")
        self._secretos[(channel, tenant_id, nombre)] = valor


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

    def release(self, *, tenant_id: str, message_id: str) -> None:
        """Borra el registro (rollback cuando el encolado posterior falla).

        Args:
            tenant_id: Comercio resuelto.
            message_id: Id del mensaje en el canal.

        Raises:
            ValidationError: Si falta `tenant_id` o `message_id`.
        """
        if not tenant_id or not message_id:
            raise ValidationError("faltan tenant_id o message_id en la liberación de dedup")
        self._vistos.discard((tenant_id, message_id))


class InMemoryEventBus:
    """`EventBusPort` de tests: captura lo publicado y puede fingir un fallo.

    Example:
        >>> from slices.conversation_gateway.infrastructure.in_memory import InMemoryEventBus
        >>> bus = InMemoryEventBus()
        >>> bus.publish("inbound.message", {"tenant_id": "Sede_Elite_01"})
        >>> bus.published[0][0]
        'inbound.message'
    """

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        """Prepara el doble, opcionalmente con una falla simulada de transporte.

        Args:
            fail_with: Excepción que `publish` debe lanzar (para probar el rollback
                de la deduplicación); `None` = publicación correcta.
        """
        self.published: list[tuple[str, dict[str, object]]] = []
        self._fail_with = fail_with

    def publish(self, event_name: str, payload: Mapping[str, object]) -> None:
        """Captura el evento en `published` o lanza la falla configurada.

        Args:
            event_name: Nombre estable del evento.
            payload: Datos ya validados contra su contrato.

        Raises:
            Exception: La falla inyectada en el constructor (simula SQS caído).
        """
        if self._fail_with is not None:
            raise self._fail_with
        self.published.append((event_name, dict(payload)))


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


@dataclass(frozen=True)
class GraphCall:
    """Captura de un POST al doble de Graph API (tipada para los tests).

    Evita `dict[str, object]` (cuyo indexador devuelve `object` y obliga a casts en
    cada test); con un dataclass los tests leen `call.url`/`call.json` tipados.

    Attributes:
        url: URL del endpoint Graph API.
        json: Cuerpo JSON enviado.
        headers: Cabeceras enviadas.
        timeout: Segundos de espera usados en la llamada.
    """

    url: str
    json: dict[str, object]
    headers: dict[str, str]
    timeout: float


class InMemoryGraphClient:
    """`GraphApiPort` de tests: captura el POST y puede fingir un estado HTTP.

    No usa red: devuelve una respuesta sintética con `status_code` fijo, para probar
    el `MetaChannel.send` (camino feliz y rechazo >= 400) sin tocar la Graph API.

    Example:
        >>> from slices.conversation_gateway.infrastructure.in_memory import InMemoryGraphClient
        >>> client = InMemoryGraphClient()
        >>> client.post(
        ...     "https://graph.facebook.com/v24.0/1/messages",
        ...     json={"messaging_product": "whatsapp"},
        ...     headers={},
        ...     timeout=10,
        ... ).status_code
        200
    """

    def __init__(self, *, status_code: int = 200) -> None:
        """Prepara el doble con el código HTTP a devolver.

        Args:
            status_code: Código que devolverá `post` (por defecto 200 = aceptado).
        """
        self.calls: list[GraphCall] = []
        self._status_code = status_code

    def post(
        self, url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float
    ) -> Response:
        """Captura la llamada y devuelve una respuesta sintética.

        Args:
            url: URL del endpoint (capturada en `calls`).
            json: Cuerpo JSON (capturado en `calls`).
            headers: Cabeceras (capturadas en `calls`).
            timeout: Segundos de espera (capturado en `calls`).

        Returns:
            `Response` fake solo con `status_code` (el adapter solo lee eso).
        """
        self.calls.append(
            GraphCall(url=url, json=dict(json), headers=dict(headers), timeout=timeout)
        )
        respuesta = Response()
        respuesta.status_code = self._status_code
        return respuesta
