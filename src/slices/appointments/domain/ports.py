"""Ports de salida del dominio de citas (Protocol): la implementación va en infrastructure/.

El dominio declara qué necesita persistir y consultar; ni DynamoDB ni Aurora aparecen
aquí. Todos los métodos reciben `tenant_id` **explícito**: el repositorio filtra por
él aunque la entidad lo lleve dentro (defensa en profundidad del aislamiento).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from .entities import Appointment


@runtime_checkable
class AppointmentRepositoryPort(Protocol):
    """Persistencia y consulta de citas, siempre limitadas a un comercio."""

    def save(self, *, tenant_id: str, appointment: Appointment) -> None:
        """Guarda la cita, reemplazando la anterior si reutiliza su `id`.

        Args:
            tenant_id: Comercio bajo el que se guarda; debe coincidir con el de la cita.
            appointment: Cita a persistir (modelo inmutable ya validado).

        Raises:
            ValidationError: Si `tenant_id` está vacío o no coincide con el de la cita.
        """
        ...

    def find(self, *, tenant_id: str, appointment_id: str) -> Appointment | None:
        """Busca una cita por su identificador dentro del comercio indicado.

        Args:
            tenant_id: Comercio cuyas citas se consultan.
            appointment_id: Identificador de la cita.

        Returns:
            La cita si existe y pertenece a `tenant_id`; `None` en cualquier otro caso
            (una cita ajena se reporta como inexistente, nunca como ajena).

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> Appointment | None:
        """Recupera la cita creada por una petición anterior (clave de idempotencia).

        Args:
            tenant_id: Comercio cuyas citas se consultan.
            correlation_id: `correlation_id` de la creación original.

        Returns:
            La cita ya creada para esa petición o `None` si no existe.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def list_for_period(
        self, *, tenant_id: str, start: datetime, end: datetime
    ) -> Sequence[Appointment]:
        """Lista las citas del comercio cuyo inicio cae dentro del periodo.

        Args:
            tenant_id: Comercio cuyas citas se consultan.
            start: Inicio del periodo (inclusive).
            end: Fin del periodo (inclusive).

        Returns:
            Citas ordenadas por `starts_at`; vacío si no hay ninguna.

        Raises:
            ValidationError: Si `start` es posterior a `end`.
        """
        ...
