"""Port de persistencia del contexto de cliente (Protocol): implementación en infrastructure/.

El dominio declara qué necesita leer y escribir; ni DynamoDB aparece aquí. Todos los
métodos reciben `tenant_id` **explícito** además de llevarlo dentro del modelo: el
almacén filtra por él aunque la entidad lo incluya (defensa en profundidad, misma
traza que `AppointmentRepositoryPort`).
"""

from typing import Protocol, runtime_checkable

from shared.contracts import CustomerContext


@runtime_checkable
class CustomerContextPort(Protocol):
    """Lectura y escritura del contexto por cliente, siempre limitadas a un comercio."""

    def get(self, *, tenant_id: str, customer_id: str) -> CustomerContext | None:
        """Devuelve el contexto del cliente dentro del comercio indicado.

        Args:
            tenant_id: Comercio cuyo contexto se consulta.
            customer_id: Identificador del cliente (teléfono normalizado).

        Returns:
            El contexto guardado o `None` si el cliente es nuevo en este comercio
            (un contexto ajeno es literalmente inencontrable).

        Raises:
            ValidationError: Si `tenant_id` o `customer_id` están vacíos.
            ContextStaleError: Si el contexto existe pero superó su TTL.
        """
        ...

    def save(self, *, tenant_id: str, context: CustomerContext) -> None:
        """Guarda el contexto, reemplazando el anterior del mismo cliente.

        Args:
            tenant_id: Comercio bajo el que se guarda; debe coincidir con el del contexto.
            context: Contexto a persistir (modelo inmutable ya validado).

        Raises:
            ValidationError: Si `tenant_id` está vacío o no coincide con el del contexto.
        """
        ...
