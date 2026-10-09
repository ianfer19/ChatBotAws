"""Drafts de acción pendiente: propose/commit fuera del agente (ADR 0011).

El LLM solo propone (`propose_*`); la plataforma confirma y ejecuta. El draft es el
estado de negocio intermedio: vive fuera del grafo, sobrevive a los turnos y su
`payload_hash` liga cualquier confirmación posterior al contenido exacto propuesto.

Contrato versionado (`schema_version`), inmutable y sin campos extra: lo que no pasa
el contrato no se almacena ni se ejecuta.
"""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.errors import ValidationError


class DraftStatus(StrEnum):
    """Estados posibles de un draft (máquina de estados del ADR 0011)."""

    DRAFTED = "drafted"
    AUTO_APPROVED = "auto_approved"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    COMMITTED = "committed"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


ACTIVE_STATUSES: frozenset[DraftStatus] = frozenset(
    {
        DraftStatus.DRAFTED,
        DraftStatus.AUTO_APPROVED,
        DraftStatus.AWAITING_CONFIRMATION,
        DraftStatus.CONFIRMED,
    }
)
"""Estados «vivos»: como máximo uno por conversación (invariante del store)."""

COMMITIBLE_STATUSES: frozenset[DraftStatus] = frozenset(
    {DraftStatus.AUTO_APPROVED, DraftStatus.CONFIRMED}
)
"""Únicos estados desde los que se acepta un commit (capa de defensa, ADR 0011.6)."""


class ConfirmationPolicy(StrEnum):
    """Decisión de la política de riesgo para un draft recién propuesto."""

    AUTO = "auto"
    CONFIRM = "confirm"


class _DraftBase(BaseModel):
    """Base común de este módulo: inmutable y sin campos extra."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyDecision(_DraftBase):
    """Resultado de `decide(draft, customer, cfg)` en el dominio de cada slice.

    Args:
        policy: `AUTO` (commit directo con ventana de deshacer) o `CONFIRM`
            (queda a la espera de la confirmación del cliente).
        reasons: Causas que motivaron la decisión (para logs, métricas y tests);
            vacías cuando la política es `AUTO` sin reservas.
    """

    schema_version: Literal[1] = 1
    policy: ConfirmationPolicy
    reasons: tuple[str, ...] = ()


class PendingDraft(_DraftBase):
    """Borrador de pedido o cita propuesto por el agente y pendiente de ejecutar.

    Un solo draft activo por conversación (lo garantiza el store); modificarlo crea un
    draft nuevo y el anterior pasa a `SUPERSEDED`. El `payload_hash` se calcula al
    crearlo con `compute_payload_hash` y no vuelve a cambiar: el payload es inmutable.

    Args:
        schema_version: Versión del contrato (añadir campos es compatible).
        draft_id: Identificador del draft; también clave de idempotencia del commit.
        tenant_id: Comercio dueño del draft (siempre del contexto, nunca del LLM).
        conversation_id: Conversación a la que pertenece (compuesto hasta el Paso 9,
            `TODO(verify)`: el identificador real lo pone el gateway).
        kind: Tipo de acción propuesta.
        status: Estado actual en la máquina de estados.
        payload: Contenido exacto propuesto (lo tipa el dominio de cada slice).
        inferred_fields: Campos que el LLM infirió en lugar de decir el cliente
            (disparan `CONFIRM` en la política).
        total: Monto total cuando aplica (0 para citas); origen: catálogo/legacy.
        payload_hash: Hash canónico del `payload` al crearse.
        correlation_id: Idempotencia de la propuesta repetida.
        created_at: Instante de creación (sale del `ClockPort`).
        expires_at: Fin de la ventana de confirmación (TTL del draft).
        undo_until: Ventana de deshacer tras un commit con política `AUTO`.
    """

    schema_version: Literal[1] = 1
    draft_id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    conversation_id: str = Field(min_length=1, max_length=128)
    kind: Literal["order", "appointment"]
    status: DraftStatus = DraftStatus.DRAFTED
    payload: dict[str, Any] = Field(default_factory=dict)
    inferred_fields: tuple[str, ...] = ()
    total: float = Field(default=0.0, ge=0)
    payload_hash: str = Field(min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)
    created_at: datetime
    expires_at: datetime
    undo_until: datetime | None = None

    def is_active(self) -> bool:
        """Indica si el draft ocupa la única ranura activa de su conversación.

        Returns:
            `True` si el estado está en `ACTIVE_STATUSES`.
        """
        return self.status in ACTIVE_STATUSES


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """Hash canónico (SHA-256) del payload de un draft.

    Serializa con claves ordenadas y sin espacios para que el mismo contenido dé
    siempre el mismo hash: es lo que enlaza un «sí» o un botón al contenido exacto.

    Args:
        payload: Contenido propuesto (debe ser JSON serializable).

    Returns:
        Hash en hexadecimal de 64 caracteres.

    Raises:
        ValidationError: Si el payload no es serializable a JSON.
    """
    try:
        canonico = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "el payload del draft no es serializable a JSON",
            details={"motivo": str(exc)},
        ) from exc
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()
