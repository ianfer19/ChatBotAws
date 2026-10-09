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


@runtime_checkable
class LegacyOpsPort(Protocol):
    """Disponibilidad y creación reales en el backend legacy (`ops_service`).

    Declarado en el Paso 5 pero sin implementación HTTP hasta el Paso 11 (llamada a
    través de AgentCore Gateway + Policy). El catálogo
    (`sahagunonline/back/docs/catalogo_endpoints.md`) detalla Sales/Product/Auth pero
    no el servicio de reservas: `TODO(verify)` — se asume el prefijo `/bookings`
    observado en `ops_service`, confirmar contra el código fuente en el Paso 11
    (ver `docs/architecture/INTEGRATION_WITH_LEGACY.md` §4).
    """

    def get_availability(self, *, tenant_id: str, date: str) -> Sequence[datetime]:
        """Huecos ocupados del día en el legacy (la disponibilidad libre es el complemento).

        Args:
            tenant_id: Comercio consultado (mapeado al `store_id` legado).
            date: Día en ISO (`YYYY-MM-DD`).

        Returns:
            Inicios de las citas ya agendadas en el legacy para ese día.

        Raises:
            ToolTimeoutError: Si el legacy no responde dentro del timeout.
        """
        ...

    def create_appointment(
        self,
        *,
        tenant_id: str,
        date: str,
        time: str,
        customer_name: str,
        contact: str,
        correlation_id: str,
    ) -> str:
        """Crea la cita en el legacy y devuelve su identificador.

        Args:
            tenant_id: Comercio de la cita.
            date: Fecha en ISO (`YYYY-MM-DD`).
            time: Hora (`HH:MM`).
            customer_name: Nombre del cliente.
            contact: Medio de contacto del cliente.
            correlation_id: Clave de idempotencia de la creación.

        Returns:
            Identificador de la cita creada en el legacy.

        Raises:
            ToolTimeoutError: Si el legacy no responde dentro del timeout.
        """
        ...

    def cancel_appointment(self, *, tenant_id: str, appointment_id: str) -> None:
        """Cancela la cita en el legacy.

        Args:
            tenant_id: Comercio dueño de la cita.
            appointment_id: Cita a cancelar.

        Raises:
            ToolTimeoutError: Si el legacy no responde dentro del timeout.
        """
        ...
