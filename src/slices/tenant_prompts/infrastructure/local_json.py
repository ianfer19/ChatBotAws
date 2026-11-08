"""Repositorio local de perfiles de comercio en JSON (Fase A de la consola).

Es deliberadamente simple: un fichero `console-data/tenants.json`, escritura atómica y
un lock de proceso. No hay secretos aquí: las credenciales de canal/POS viven en SSM
en las fases de producción. El fichero se ignora en git; el ejemplo versionado sirve
como semilla documentada.
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from shared.errors import ValidationError
from shared.logging import get_logger
from slices.tenant_prompts.domain.entities import TenantProfile
from slices.tenant_prompts.domain.ports import TenantProfileRepositoryPort

logger = get_logger(__name__)

_FORMATO = 1


class LocalJsonTenantRepository(TenantProfileRepositoryPort):
    """`TenantProfileRepositoryPort` sobre un único JSON local.

    Args:
        path: Ruta del fichero; se crea con `seed` si no existe.
        seed: Perfil inicial para un repo vacío (la consola siembra `Sede_Elite_01`).

    Example:
        >>> from pathlib import Path
        >>> from slices.tenant_prompts.domain.entities import default_profile
        >>> repo = LocalJsonTenantRepository(
        ...     Path("console-data/tenants.json"), seed=default_profile()
        ... )
        >>> repo.get("Sede_Elite_01").display_name
        'Sede Elite'
    """

    def __init__(self, path: Path, *, seed: TenantProfile | None = None) -> None:
        """Prepara el fichero y siembra el perfil inicial si hace falta.

        Args:
            path: Ruta del JSON de perfiles.
            seed: Perfil a escribir cuando el fichero no existe.
        """
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            inicial = {seed.tenant_id: seed} if seed is not None else {}
            self._escribir(inicial)

    def list(self) -> list[TenantProfile]:
        """Devuelve todos los perfiles ordenados por `tenant_id`.

        Returns:
            Lista de perfiles validados.
        """
        with self._lock:
            datos = self._leer()
        return [datos[clave] for clave in sorted(datos)]

    def get(self, tenant_id: str) -> TenantProfile | None:
        """Devuelve el perfil del comercio o `None`.

        Args:
            tenant_id: Comercio consultado.
        """
        with self._lock:
            return self._leer().get(tenant_id)

    def save(self, profile: TenantProfile) -> None:
        """Crea o reemplaza el perfil y persiste el fichero completo.

        Args:
            profile: Perfil validado que se guarda.

        Raises:
            ValidationError: Si el fichero existente no tiene el formato esperado.
        """
        with self._lock:
            datos = self._leer()
            datos[profile.tenant_id] = profile
            self._escribir(datos)
        logger.info("console.tenant_persisted", extra={"tenant_id": profile.tenant_id})

    def _leer(self) -> dict[str, TenantProfile]:
        """Lee y valida el JSON de perfiles.

        Returns:
            Diccionario `tenant_id -> TenantProfile`.

        Raises:
            ValidationError: Si el JSON está corrupto o no tiene el formato esperado.
        """
        try:
            crudo = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "el JSON de la consola no es válido",
                details={"path": str(self._path)},
            ) from exc
        if not isinstance(crudo, dict) or crudo.get("version") != _FORMATO:
            raise ValidationError(
                "el JSON de la consola tiene un formato desconocido",
                details={"path": str(self._path)},
            )
        tenants = crudo.get("tenants")
        if not isinstance(tenants, dict):
            raise ValidationError(
                "el JSON de la consola no contiene 'tenants'",
                details={"path": str(self._path)},
            )
        try:
            return {
                str(tenant_id): TenantProfile.model_validate(datos)
                for tenant_id, datos in tenants.items()
            }
        except PydanticValidationError as exc:
            raise ValidationError(
                "un perfil de la consola no cumple el esquema",
                details={"path": str(self._path)},
            ) from exc

    def _escribir(self, datos: dict[str, TenantProfile]) -> None:
        """Escribe el JSON de forma atómica (temporal + `os.replace`).

        Args:
            datos: Perfiles a persistir.

        Raises:
            ValidationError: Si el fichero no se puede escribir.
        """
        contenido: dict[str, Any] = {
            "version": _FORMATO,
            "tenants": {
                tenant_id: profile.model_dump(mode="json") for tenant_id, profile in datos.items()
            },
        }
        temporal: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as archivo:
                json.dump(contenido, archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
                temporal = archivo.name
            os.replace(temporal, self._path)
            temporal = None
        except OSError as exc:
            raise ValidationError(
                "no se pudo escribir el JSON de la consola",
                details={"path": str(self._path)},
            ) from exc
        finally:
            if temporal is not None:
                Path(temporal).unlink(missing_ok=True)
