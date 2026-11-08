"""Casos de uso de la consola local: perfil del comercio y overrides de prompt.

Esta capa orquesta el repositorio de perfiles y las plantillas base; no conoce FastAPI
ni AWS. La Fase B sustituirá el repositorio local por uno respaldado por Bedrock Prompt
Management y DynamoDB, manteniendo estos mismos casos de uso.
"""

from pathlib import Path

from shared.logging import get_logger
from slices.tenant_prompts.application.models import PromptInfo, PromptView
from slices.tenant_prompts.domain.entities import (
    PROMPT_KINDS,
    PromptKind,
    TenantProfile,
    TenantProfileUpdate,
)
from slices.tenant_prompts.domain.errors import (
    PromptOverrideInvalidError,
    TenantProfileNotFoundError,
)
from slices.tenant_prompts.domain.ports import TenantProfileRepositoryPort

logger = get_logger(__name__)

_MAX_PROMPT_CHARS = 50_000
"""Tope defensivo para un prompt editable; evita payloads gigantes en la consola."""


class TenantConfigService:
    """Perfil y prompts editables de un comercio (Fase A, persistencia local).

    Args:
        repository: Store de perfiles (JSON local en la Fase A).
        base_prompt_dir: Directorio de plantillas base; por defecto `prompts/base/`.
    """

    def __init__(
        self,
        *,
        repository: TenantProfileRepositoryPort,
        base_prompt_dir: Path | None = None,
    ) -> None:
        """Guarda el repositorio y resuelve la ruta de las plantillas base.

        Args:
            repository: Store de perfiles ya inicializado.
            base_prompt_dir: Ruta alternativa para tests; `None` usa la del repo.
        """
        self._repository = repository
        self._base_prompt_dir = base_prompt_dir or (
            Path(__file__).resolve().parents[4] / "prompts" / "base"
        )

    def list_tenants(self) -> list[TenantProfile]:
        """Devuelve todos los comercios configurados en la consola.

        Returns:
            Perfiles ordenados por `tenant_id`.
        """
        return self._repository.list()

    def get_tenant(self, tenant_id: str) -> TenantProfile:
        """Recupera un perfil o lanza el error tipado de la API.

        Args:
            tenant_id: Comercio consultado.

        Returns:
            El perfil guardado.

        Raises:
            TenantProfileNotFoundError: Si el comercio no existe.
        """
        profile = self._repository.get(tenant_id)
        if profile is None:
            raise TenantProfileNotFoundError(
                "no existe perfil para el comercio",
                details={"tenant_id": tenant_id},
            )
        return profile

    def update_tenant(self, tenant_id: str, update: TenantProfileUpdate) -> TenantProfile:
        """Aplica solo los campos enviados y guarda el perfil validado.

        Args:
            tenant_id: Comercio a modificar.
            update: Campos opcionales ya validados por Pydantic.

        Returns:
            El perfil actualizado.

        Raises:
            TenantProfileNotFoundError: Si el comercio no existe.
        """
        actual = self.get_tenant(tenant_id)
        cambios = update.model_dump(exclude_unset=True)
        # Un `null` explícito solo tiene sentido para limpiar `model_id`; en el resto
        # de campos se ignora para no borrar configuración por accidente.
        for campo in ("display_name", "tone", "language"):
            if cambios.get(campo) is None:
                cambios.pop(campo, None)
        if cambios.get("allowed_bots") is None:
            cambios.pop("allowed_bots", None)
        actualizado = TenantProfile.model_validate(
            {**actual.model_dump(), **cambios, "tenant_id": tenant_id}
        )
        self._repository.save(actualizado)
        logger.info("console.tenant_updated", extra={"tenant_id": tenant_id})
        return actualizado

    def prompt_for(self, tenant_id: str, kind: PromptKind) -> str | None:
        """Devuelve el override del comercio o `None` si debe usarse la plantilla base.

        Args:
            tenant_id: Comercio cuyo prompt se consulta.
            kind: Tipo de prompt.

        Returns:
            El contenido propio o `None` (la composición deja que el grafo cargue la
            plantilla base).
        """
        try:
            profile = self.get_tenant(tenant_id)
        except TenantProfileNotFoundError:
            return None
        return profile.prompts.get(kind)

    def list_prompts(self, tenant_id: str) -> list[PromptInfo]:
        """Lista los prompts editables con su origen y longitud efectiva.

        Args:
            tenant_id: Comercio consultado.

        Returns:
            Un `PromptInfo` por tipo en `PROMPT_KINDS`.

        Raises:
            TenantProfileNotFoundError: Si el comercio no existe.
        """
        profile = self.get_tenant(tenant_id)
        resultado: list[PromptInfo] = []
        for kind in PROMPT_KINDS:
            override = profile.prompts.get(kind)
            contenido = override if override is not None else self.base_prompt(kind)
            resultado.append(
                PromptInfo(
                    kind=kind,
                    is_override=override is not None,
                    length=len(contenido),
                )
            )
        return resultado

    def get_prompt(self, tenant_id: str, kind: PromptKind) -> PromptView:
        """Devuelve el contenido efectivo y la plantilla base de un prompt.

        Args:
            tenant_id: Comercio consultado.
            kind: Tipo de prompt.

        Returns:
            La vista con override (si existe) o la base.

        Raises:
            TenantProfileNotFoundError: Si el comercio no existe.
        """
        profile = self.get_tenant(tenant_id)
        base = self.base_prompt(kind)
        override = profile.prompts.get(kind)
        return PromptView(
            kind=kind,
            content=override if override is not None else base,
            is_override=override is not None,
            base_content=base,
        )

    def update_prompt(self, tenant_id: str, kind: PromptKind, content: str) -> PromptView:
        """Guarda un override de prompt para el comercio.

        Args:
            tenant_id: Comercio a modificar.
            kind: Tipo de prompt.
            content: Texto nuevo del prompt.

        Returns:
            La vista actualizada.

        Raises:
            PromptOverrideInvalidError: Si el texto está vacío o supera el tope.
            TenantProfileNotFoundError: Si el comercio no existe.
        """
        texto = content.strip()
        if not texto:
            raise PromptOverrideInvalidError("el prompt no puede estar vacío")
        if len(texto) > _MAX_PROMPT_CHARS:
            raise PromptOverrideInvalidError(
                "el prompt supera el máximo permitido",
                details={"max": str(_MAX_PROMPT_CHARS)},
            )
        profile = self.get_tenant(tenant_id)
        prompts = {**profile.prompts, kind: texto}
        self._repository.save(
            TenantProfile.model_validate({**profile.model_dump(), "prompts": prompts})
        )
        logger.info(
            "console.prompt_updated",
            extra={"tenant_id": tenant_id, "kind": kind, "chars": str(len(texto))},
        )
        return self.get_prompt(tenant_id, kind)

    def reset_prompt(self, tenant_id: str, kind: PromptKind) -> PromptView:
        """Elimina el override y vuelve a la plantilla base.

        Args:
            tenant_id: Comercio a modificar.
            kind: Tipo de prompt.

        Returns:
            La vista con la plantilla base.

        Raises:
            TenantProfileNotFoundError: Si el comercio no existe.
        """
        profile = self.get_tenant(tenant_id)
        prompts = {clave: valor for clave, valor in profile.prompts.items() if clave != kind}
        self._repository.save(
            TenantProfile.model_validate({**profile.model_dump(), "prompts": prompts})
        )
        logger.info(
            "console.prompt_reset",
            extra={"tenant_id": tenant_id, "kind": kind},
        )
        return self.get_prompt(tenant_id, kind)

    def base_prompt(self, kind: PromptKind) -> str:
        """Lee la plantilla base compartida desde `prompts/base/`.

        Args:
            kind: Tipo de prompt; coincide con el nombre del fichero `.md`.

        Returns:
            El contenido de la plantilla base.

        Raises:
            PromptOverrideInvalidError: Si el fichero base falta o está vacío (error de
                despliegue, no del usuario).
        """
        ruta = self._base_prompt_dir / f"{kind}.md"
        try:
            contenido = ruta.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromptOverrideInvalidError(
                "no se pudo cargar la plantilla base",
                details={"ruta": str(ruta)},
            ) from exc
        if not contenido.strip():
            raise PromptOverrideInvalidError(
                "la plantilla base está vacía",
                details={"ruta": str(ruta)},
            )
        return contenido
