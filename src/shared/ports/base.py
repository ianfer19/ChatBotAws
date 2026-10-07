"""Ports transversales (`Protocol`); las implementaciones concretas viven en adapters.

El dominio y la aplicación dependen de estas interfaces, nunca de boto3 ni de HTTP.
En tests se sustituyen por dobles de una línea (DI manual, sin framework).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class ClockPort(Protocol):
    """Reloj inyectable: el dominio no llama a `datetime.now()` directamente."""

    def now(self) -> datetime:
        """Fecha y hora actuales conscientes de la zona horaria (UTC en producción)."""
        ...


@runtime_checkable
class LLMPort(Protocol):
    """Generación de texto sobre el modelo tras un port intercambiable (ADR 0004)."""

    def complete(self, *, system: str, prompt: str, max_tokens: int | None = None) -> str:
        """Invoca al modelo y devuelve la respuesta como texto plano.

        Args:
            system: Instrucciones de sistema (plantilla ya renderizada).
            prompt: Entrada del turno actual.
            max_tokens: Tope de salida opcional; el adapter aplica el del modelo si es None.

        Returns:
            Texto de la respuesta, sin parsear (el llamador aplica su contrato).
        """
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
