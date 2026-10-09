"""Tool de lectura `get_customer_context` y caso de uso de escritura (Paso 4).

La tool es de solo lectura para el LLM y **no recibe parámetros desde el modelo**: el
nodo del turno inyecta `tenant_id` (contexto resuelto en el gateway) y `customer_id`
(identificador del canal) desde el estado — nunca desde el payload del modelo (reglas
3 y 4 del slice). La escritura (`update_customer_context`) **no es tool**: solo la
disparan eventos del pipeline, jamás una invocación del modelo.

El contexto nunca contiene verdad operacional (precios, stock, pedidos ni horas): solo
identificación y preferencias (contrato `shared.contracts.CustomerContext`).
"""

from collections.abc import Sequence

from shared.contracts import CustomerContext
from shared.errors import ValidationError
from shared.logging import get_logger
from shared.ports import ClockPort
from slices.customer_context.domain.errors import ContextStaleError
from slices.customer_context.domain.ports import CustomerContextPort

_logger = get_logger(__name__)


def _require_identificadores(tenant_id: str, customer_id: str) -> None:
    """Rechaza llamadas sin comercio o sin cliente: nada trabaja «a ciegas».

    Args:
        tenant_id: Comercio resuelto en el gateway.
        customer_id: Cliente normalizado del canal.

    Raises:
        ValidationError: Si alguno de los dos viene vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en las tools de contexto")
    if not customer_id:
        raise ValidationError("customer_id vacío en las tools de contexto")


def _vacio(tenant_id: str, customer_id: str) -> CustomerContext:
    """Construye el contexto por defecto de un cliente sin historial.

    Args:
        tenant_id: Comercio del turno.
        customer_id: Cliente del turno.

    Returns:
        Contexto inmutable con los identificadores y el resto en sus defaults.
    """
    return CustomerContext(tenant_id=tenant_id, customer_id=customer_id)


class CustomerContextTools:
    """Lectura obligatoria por turno y escritura por eventos del contexto de cliente."""

    def __init__(self, *, store: CustomerContextPort, clock: ClockPort) -> None:
        """Prepara las herramientas con su almacén y su reloj.

        Args:
            store: Persistencia del contexto (en memoria hasta el Paso 6).
            clock: Reloj para sellar `last_seen_at` en cada escritura.
        """
        self._store = store
        self._clock = clock

    def get_customer_context(self, *, tenant_id: str, customer_id: str) -> CustomerContext:
        """Tool `get_customer_context`: lectura obligatoria de cada turno (regla 1).

        Args:
            tenant_id: Comercio, **inyectado por el nodo desde el estado** (no del LLM).
            customer_id: Cliente, inyectado igual por el nodo.

        Returns:
            El contexto guardado; contexto vacío si el cliente es nuevo o si el TTL
            venció (ninguno de los dos es un error para el turno).

        Raises:
            ValidationError: Si falta `tenant_id` o `customer_id`.
        """
        _require_identificadores(tenant_id, customer_id)
        try:
            almacenado = self._store.get(tenant_id=tenant_id, customer_id=customer_id)
        except ContextStaleError:
            _logger.info("customer_context.stale", extra={"tenant_id": tenant_id})
            return _vacio(tenant_id, customer_id)
        if almacenado is None:
            return _vacio(tenant_id, customer_id)
        return almacenado

    def update_customer_context(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        name: str | None = None,
        preferences: dict[str, str] | None = None,
        tags: Sequence[str] | None = None,
    ) -> CustomerContext:
        """Caso de uso de escritura (eventos del pipeline; **no es tool del LLM**, regla 4).

        Fusiona lo nuevo sobre lo existente: las preferencias nuevas ganan, las etiquetas
        se acumulan sin duplicar y `last_seen_at` se sella con el reloj inyectado.

        Args:
            tenant_id: Comercio del evento, del contexto resuelto.
            customer_id: Cliente del evento.
            name: Nombre a establecer (si viene); `None` conserva el actual.
            preferences: Preferencias a fusionar (ganan sobre las existentes).
            tags: Etiquetas a añadir (se acumulan sin duplicados).

        Returns:
            El contexto ya persistido tras la fusión.

        Raises:
            ValidationError: Si faltan identificadores o el tenant no coincide.
        """
        _require_identificadores(tenant_id, customer_id)
        try:
            actual = self._store.get(tenant_id=tenant_id, customer_id=customer_id)
        except ContextStaleError:
            actual = None
        base = actual if actual is not None else _vacio(tenant_id, customer_id)
        etiquetas = list(base.tags)
        for tag in tags or ():
            if tag not in etiquetas:
                etiquetas.append(tag)
        contexto = CustomerContext(
            tenant_id=tenant_id,
            customer_id=customer_id,
            name=name if name is not None else base.name,
            preferences={**base.preferences, **(preferences or {})},
            tags=etiquetas,
            last_seen_at=self._clock.now(),
        )
        self._store.save(tenant_id=tenant_id, context=contexto)
        return contexto
