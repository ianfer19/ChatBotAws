"""Ports transversales (`Protocol`); las implementaciones concretas viven en adapters.

El dominio y la aplicación dependen de estas interfaces, nunca de boto3 ni de HTTP.
En tests se sustituyen por dobles de una línea (DI manual, sin framework).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

# El modelo de lenguaje vive en `shared.ports.llm` (firma Converse); aquí solo quedan
# los ports de utilidad pura (reloj y bus de eventos).


@runtime_checkable
class ClockPort(Protocol):
    """Reloj inyectable: el dominio no llama a `datetime.now()` directamente."""

    def now(self) -> datetime:
        """Fecha y hora actuales conscientes de la zona horaria (UTC en producción)."""
        ...


@runtime_checkable
class EventBusPort(Protocol):
    """Publicación de eventos hacia otros slices (cola en dev/prod, doble en tests)."""

    def publish(self, event_name: str, payload: Mapping[str, object]) -> None:
        """Publica un payload serializable a JSON bajo un nombre de evento.

        Args:
            event_name: Nombre estable del evento (p. ej. `inbound.message`).
            payload: Datos ya validados contra su contrato de `shared/contracts`.

        Raises:
            ToolError: Si el transporte falla (lo traduce el adapter).
        """
        ...
