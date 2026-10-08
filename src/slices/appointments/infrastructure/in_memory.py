"""Repositorio de citas en memoria: doble de tests y desarrollo previo a la infraestructura.

Existe desde el Paso 1 porque la batería debe poder probar el dominio sin DynamoDB ni
Aurora (ROADMAP §2.4: "fakes hasta la infraestructura"). En el Paso 6 se añade el
adapter real implementando el mismo `AppointmentRepositoryPort`, sin tocar el dominio.

El aislamiento por tenant está en la propia clave del diccionario `(tenant_id, id)`:
una cita de otro comercio es literalmente inencontrable.
"""

from collections.abc import Sequence
from datetime import datetime

from shared.errors import ValidationError
from slices.appointments.domain.entities import Appointment


def _require_tenant(tenant_id: str) -> None:
    """Rechaza operaciones sin comercio: ningún método trabaja "a ciegas".

    Args:
        tenant_id: Comercio resuelto en el gateway.

    Raises:
        ValidationError: Si `tenant_id` está vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en el repositorio de citas")


class InMemoryAppointmentRepository:
    """`AppointmentRepositoryPort` sobre un diccionario de proceso único.

    Example:
        >>> repo = InMemoryAppointmentRepository()
        >>> repo.find(tenant_id="Sede_Elite_01", appointment_id="c-1") is None
        True
    """

    def __init__(self) -> None:
        self._appointments: dict[tuple[str, str], Appointment] = {}

    @staticmethod
    def _key(tenant_id: str, appointment_id: str) -> tuple[str, str]:
        """Clave canónica de almacenamiento: separa los comercios desde el origen.

        Args:
            tenant_id: Comercio dueño de la cita.
            appointment_id: Identificador de la cita.

        Returns:
            Tupla `(tenant_id, appointment_id)` usada como clave.
        """
        return (tenant_id, appointment_id)

    def save(self, *, tenant_id: str, appointment: Appointment) -> None:
        """Guarda la cita bajo el tenant indicado (sobrescribe si ya existía).

        Args:
            tenant_id: Comercio bajo el que se guarda.
            appointment: Cita a persistir.

        Raises:
            ValidationError: Si `tenant_id` está vacío o difiere del de la cita.
        """
        _require_tenant(tenant_id)
        if appointment.tenant_id != tenant_id:
            raise ValidationError(
                "la cita pertenece a otro comercio",
                details={"tenant_solicitado": tenant_id, "tenant_cita": appointment.tenant_id},
            )
        self._appointments[self._key(tenant_id, appointment.id)] = appointment

    def find(self, *, tenant_id: str, appointment_id: str) -> Appointment | None:
        """Devuelve la cita del tenant indicado o `None` si no existe.

        Args:
            tenant_id: Comercio cuyas citas se consultan.
            appointment_id: Identificador de la cita.

        Returns:
            La cita o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return self._appointments.get(self._key(tenant_id, appointment_id))

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> Appointment | None:
        """Devuelve la cita creada por esa petición (idempotencia) o `None`.

        Args:
            tenant_id: Comercio cuyas citas se consultan.
            correlation_id: Clave de idempotencia de la creación.

        Returns:
            La cita o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        for (stored_tenant, _), appointment in self._appointments.items():
            if stored_tenant == tenant_id and appointment.correlation_id == correlation_id:
                return appointment
        return None

    def list_for_period(
        self, *, tenant_id: str, start: datetime, end: datetime
    ) -> Sequence[Appointment]:
        """Devuelve las citas del tenant cuyo inicio cae en el periodo (inclusivo).

        Args:
            tenant_id: Comercio cuyas citas se consultan.
            start: Inicio del periodo (inclusive).
            end: Fin del periodo (inclusive).

        Returns:
            Citas ordenadas por `starts_at`.

        Raises:
            ValidationError: Si el periodo viene invertido.
        """
        _require_tenant(tenant_id)
        if start > end:
            raise ValidationError(
                "periodo invertido en el repositorio de citas",
                details={"start": start.isoformat(), "end": end.isoformat()},
            )
        in_period = [
            appointment
            for (stored_tenant, _), appointment in self._appointments.items()
            if stored_tenant == tenant_id and start <= appointment.starts_at <= end
        ]
        return sorted(in_period, key=lambda appointment: appointment.starts_at)
