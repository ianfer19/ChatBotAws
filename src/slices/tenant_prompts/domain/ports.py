"""Port de persistencia del perfil de comercio (Protocol).

El dominio declara qué necesita; la Fase A lo implementa con un JSON local y la Fase B
podrá añadir un adapter de DynamoDB sin cambiar la aplicación. Todos los métodos
reciben el `tenant_id` explícito para que el aislamiento no dependa del llamador.
"""

from typing import Protocol, runtime_checkable

from .entities import TenantProfile


@runtime_checkable
class TenantProfileRepositoryPort(Protocol):
    """Lectura y escritura de perfiles por comercio."""

    def list(self) -> list[TenantProfile]:
        """Devuelve todos los perfiles guardados, ordenados por `tenant_id`.

        Returns:
            Lista de perfiles; vacía si el almacén no tiene ninguno.
        """
        ...

    def get(self, tenant_id: str) -> TenantProfile | None:
        """Devuelve el perfil del comercio o `None` si no existe.

        Args:
            tenant_id: Comercio consultado.
        """
        ...

    def save(self, profile: TenantProfile) -> None:
        """Crea o reemplaza el perfil completo del comercio.

        Args:
            profile: Perfil ya validado e inmutable.
        """
        ...
