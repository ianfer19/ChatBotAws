"""Contexto de cliente en memoria con TTL: doble hasta la infraestructura real (Paso 6).

Existe desde el Paso 4 porque el criterio del supervisor (contexto obligatorio por
turno) debe poder probarse sin DynamoDB. En el Paso 6 se añade el adapter real sobre
la tabla `customer_context` (PK `ORG#<tenant_id>#CUST#<customer_id>`) implementando
este mismo `CustomerContextPort`, sin tocar application ni domain.

La clave `(tenant_id, customer_id)` separa los comercios desde el origen: el contexto
de un cliente en otro comercio es inencontrable, igual que en el repositorio de citas.
"""

from datetime import datetime, timedelta

from shared.contracts import CustomerContext
from shared.errors import ValidationError
from shared.ports import ClockPort
from slices.customer_context.domain.errors import ContextStaleError

_TTL_DEFECTO = timedelta(days=30)
"""Caducidad del contexto inactivo; `TODO(decision)`: valor exacto con DynamoDB (Paso 6)."""


def _require_identificadores(tenant_id: str, customer_id: str) -> None:
    """Rechaza operaciones sin comercio o sin cliente: nada trabaja «a ciegas».

    Args:
        tenant_id: Comercio resuelto en el gateway.
        customer_id: Cliente normalizado del canal.

    Raises:
        ValidationError: Si alguno de los dos viene vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en el almacén de contexto")
    if not customer_id:
        raise ValidationError("customer_id vacío en el almacén de contexto")


class InMemoryCustomerContextStore:
    """`CustomerContextPort` sobre un diccionario de proceso único, con TTL por escritura.

    Example:
        >>> from datetime import datetime
        >>> class _Reloj:
        ...     def now(self) -> datetime:
        ...         return datetime(2026, 3, 2, 8, 0)
        >>> store = InMemoryCustomerContextStore(clock=_Reloj())
        >>> store.get(tenant_id="Sede_Elite_01", customer_id="57300111111") is None
        True
    """

    def __init__(self, *, clock: ClockPort, ttl: timedelta = _TTL_DEFECTO) -> None:
        """Prepara el almacén con su reloj (para medir el TTL) y su caducidad.

        Args:
            clock: Reloj inyectable: el TTL se mide contra la hora de escritura.
            ttl: Caducidad del contexto desde la última escritura.
        """
        self._clock = clock
        self._ttl = ttl
        self._entries: dict[tuple[str, str], tuple[CustomerContext, datetime]] = {}

    @staticmethod
    def _key(tenant_id: str, customer_id: str) -> tuple[str, str]:
        """Clave canónica de almacenamiento: separa los comercios desde el origen.

        Args:
            tenant_id: Comercio dueño del contexto.
            customer_id: Cliente dueño del contexto.

        Returns:
            Tupla `(tenant_id, customer_id)` usada como clave.
        """
        return (tenant_id, customer_id)

    def get(self, *, tenant_id: str, customer_id: str) -> CustomerContext | None:
        """Devuelve el contexto vigente del cliente o `None` si es nuevo.

        Args:
            tenant_id: Comercio cuyo contexto se consulta.
            customer_id: Cliente cuyo contexto se consulta.

        Returns:
            El contexto si existe y no caducó; `None` si no existe para ese comercio.

        Raises:
            ValidationError: Si falta `tenant_id` o `customer_id`.
            ContextStaleError: Si el contexto existe pero superó su TTL (la relectura
                la decide el caso de uso en el siguiente turno).
        """
        _require_identificadores(tenant_id, customer_id)
        entrada = self._entries.get(self._key(tenant_id, customer_id))
        if entrada is None:
            return None
        contexto, guardado_en = entrada
        if self._clock.now() - guardado_en > self._ttl:
            raise ContextStaleError(
                "contexto de cliente caducado",
                details={"tenant_id": tenant_id},
            )
        return contexto

    def save(self, *, tenant_id: str, context: CustomerContext) -> None:
        """Guarda el contexto bajo el tenant indicado y reinicia su TTL.

        Args:
            tenant_id: Comercio bajo el que se guarda.
            context: Contexto a persistir.

        Raises:
            ValidationError: Si `tenant_id` viene vacío o difiere del del contexto.
        """
        _require_identificadores(tenant_id, context.customer_id)
        if context.tenant_id != tenant_id:
            raise ValidationError(
                "el contexto pertenece a otro comercio",
                details={"tenant_solicitado": tenant_id, "tenant_contexto": context.tenant_id},
            )
        self._entries[self._key(tenant_id, context.customer_id)] = (context, self._clock.now())
