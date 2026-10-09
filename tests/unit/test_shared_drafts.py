"""Contratos de drafts y las tres invariantes del `InMemoryDraftStore` (ADR 0011).

Cubre: hash canónico, inmutabilidad/aislamiento del contrato, un solo draft activo
por conversación, integridad `payload_hash`, commit solo desde `AUTO_APPROVED`/
`CONFIRMED`, expiración perezosa y ventana de deshacer.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from adapters.in_memory import InMemoryDraftStore
from shared.contracts import (
    ConfirmationPolicy,
    DraftStatus,
    PendingDraft,
    PolicyDecision,
    compute_payload_hash,
)
from shared.errors import ValidationError
from shared.ports import DraftStorePort

_AHORA = datetime(2026, 3, 2, 8, 0)
_TENANT = "Sede_Elite_01"
_OTRO_TENANT = "Otro_Comercio"
_CONVERSACION = "57300111111"
_PAYLOAD: dict[str, Any] = {"items": [{"sku": "p1", "quantity": 1}]}


class _RelojFijo:
    """Reloj controlable para TTL y ventana de deshacer."""

    def __init__(self) -> None:
        self._ahora = _AHORA

    def now(self) -> datetime:
        """Instante actual del doble.

        Returns:
            La hora configurada.
        """
        return self._ahora

    def avanzar(self, delta: timedelta) -> None:
        """Mueve el reloj hacia delante.

        Args:
            delta: Tiempo a sumar al instante actual.
        """
        self._ahora += delta


def _draft(
    *,
    draft_id: str = "d-1",
    status: DraftStatus = DraftStatus.AWAITING_CONFIRMATION,
    payload: dict[str, Any] | None = None,
    payload_hash: str | None = None,
    expires_at: datetime | None = None,
    undo_until: datetime | None = None,
    correlation_id: str | None = None,
    tenant_id: str = _TENANT,
    conversation_id: str = _CONVERSACION,
) -> PendingDraft:
    """Construye un draft de prueba con hash coherente salvo que se pida lo contrario.

    Args:
        draft_id: Identificador del draft.
        status: Estado inicial.
        payload: Contenido propuesto; por defecto un pedido mínimo.
        payload_hash: Hash forzado (para el test de integridad).
        expires_at: Fin de la ventana de confirmación.
        undo_until: Ventana de deshacer.
        correlation_id: Idempotencia de la propuesta.
        tenant_id: Comercio dueño.
        conversation_id: Conversación dueña.

    Returns:
        El draft ya validado contra el contrato.
    """
    contenido = _PAYLOAD if payload is None else payload
    return PendingDraft(
        draft_id=draft_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        kind="order",
        status=status,
        payload=contenido,
        payload_hash=(compute_payload_hash(contenido) if payload_hash is None else payload_hash),
        correlation_id=correlation_id,
        created_at=_AHORA,
        expires_at=expires_at if expires_at is not None else _AHORA + timedelta(minutes=15),
        undo_until=undo_until,
    )


def _store() -> tuple[InMemoryDraftStore, _RelojFijo]:
    """Construye el store con su reloj controlable.

    Returns:
        Tupla `(store, reloj)`.
    """
    reloj = _RelojFijo()
    return InMemoryDraftStore(clock=reloj), reloj


def test_el_doble_cumple_el_puerto() -> None:
    """El doble en memoria es sustituible por cualquier otra implementación."""
    store, _ = _store()
    assert isinstance(store, DraftStorePort)


def test_el_contrato_es_inmutable_y_sin_campos_extra() -> None:
    """`extra=forbid` rechaza campos ajenos (p. ej. un `tenant_id` inyectado)."""
    with pytest.raises(PydanticValidationError):
        PendingDraft.model_validate({**_draft().model_dump(), "tenant_id_ajeno": "x"})


def test_round_trip_del_contrato() -> None:
    """El draft sobrevive a `model_dump` → `model_validate` sin cambios."""
    original = _draft(status=DraftStatus.AUTO_APPROVED, correlation_id="corr-1")
    recuperado = PendingDraft.model_validate(original.model_dump(mode="json"))
    assert recuperado == original


def test_policy_decision_con_reglas_vacias_es_auto() -> None:
    """Sin `reasons` la política es `AUTO` (el caso de «lo de siempre»)."""
    decision = PolicyDecision(policy=ConfirmationPolicy.AUTO)
    assert decision.policy is ConfirmationPolicy.AUTO
    assert decision.reasons == ()


def test_payload_hash_canonico_e_insensible_al_orden() -> None:
    """El mismo contenido da el mismo hash sea cual sea el orden de las claves."""
    contenido: dict[str, Any] = {"a": 1, "b": 2}
    invertido: dict[str, Any] = {"b": 2, "a": 1}
    assert compute_payload_hash(contenido) == compute_payload_hash(invertido)
    assert compute_payload_hash({}) == hashlib.sha256(b"{}").hexdigest()
    assert compute_payload_hash(contenido) != compute_payload_hash({"a": 1, "b": 3})


def test_save_y_get_con_aislamiento_por_tenant() -> None:
    """Lo guardado en un comercio no se ve desde otro (regla 2 de orders)."""
    store, _ = _store()
    store.save(tenant_id=_TENANT, draft=_draft())
    assert store.get(tenant_id=_TENANT, draft_id="d-1") is not None
    assert store.get(tenant_id=_OTRO_TENANT, draft_id="d-1") is None


def test_save_rechaza_un_draft_de_otro_comercio() -> None:
    """El store no acepta escribir un draft cuyo `tenant_id` no coincide."""
    store, _ = _store()
    with pytest.raises(ValidationError, match="otro comercio"):
        store.save(tenant_id=_OTRO_TENANT, draft=_draft(tenant_id=_TENANT))


def test_un_solo_draft_activo_por_conversacion() -> None:
    """Un draft activo nuevo supersede al anterior de la misma conversación."""
    store, _ = _store()
    store.save(tenant_id=_TENANT, draft=_draft(draft_id="d-1"))
    store.save(tenant_id=_TENANT, draft=_draft(draft_id="d-2"))
    assert store.get_active(tenant_id=_TENANT, conversation_id=_CONVERSACION).draft_id == "d-2"  # type: ignore[union-attr]
    assert store.get(tenant_id=_TENANT, draft_id="d-1").status is DraftStatus.SUPERSEDED  # type: ignore[union-attr]


def test_integridad_del_payload_hash() -> None:
    """No se guarda un draft cuyo `payload_hash` no corresponde a su `payload`."""
    store, _ = _store()
    corrupto = _draft(payload_hash="f" * 64)
    with pytest.raises(ValidationError, match="payload_hash"):
        store.save(tenant_id=_TENANT, draft=corrupto)


@pytest.mark.parametrize(
    "previo",
    [DraftStatus.AUTO_APPROVED, DraftStatus.CONFIRMED],
    ids=["desde_auto", "desde_confirmado"],
)
def test_commit_desde_un_estado_compatible(previo: DraftStatus) -> None:
    """`COMMITTED` es legal solo después de `AUTO_APPROVED` o `CONFIRMED`."""
    store, _ = _store()
    store.save(tenant_id=_TENANT, draft=_draft(status=previo))
    store.save(tenant_id=_TENANT, draft=_draft(status=DraftStatus.COMMITTED))


def test_commit_desde_un_estado_ilegal_se_rechaza() -> None:
    """Aunque el agente lo pidiera, un borrador sin confirmar no se commitea."""
    store, _ = _store()
    store.save(tenant_id=_TENANT, draft=_draft(status=DraftStatus.AWAITING_CONFIRMATION))
    with pytest.raises(ValidationError, match="commit ilegal"):
        store.save(tenant_id=_TENANT, draft=_draft(status=DraftStatus.COMMITTED))


def test_commit_sin_draft_previo_se_rechaza() -> None:
    """Un `COMMITTED` de origen (sin borrador previo) también es ilegal."""
    store, _ = _store()
    with pytest.raises(ValidationError, match="commit ilegal"):
        store.save(tenant_id=_TENANT, draft=_draft(status=DraftStatus.COMMITTED))


def test_expiracion_perezosa_libera_la_ranura_activa() -> None:
    """Un draft activo caducado se marca `EXPIRED` y deja de estar activo."""
    store, reloj = _store()
    store.save(
        tenant_id=_TENANT,
        draft=_draft(expires_at=_AHORA + timedelta(minutes=15)),
    )
    assert store.get_active(tenant_id=_TENANT, conversation_id=_CONVERSACION) is not None
    reloj.avanzar(timedelta(minutes=16))
    assert store.get_active(tenant_id=_TENANT, conversation_id=_CONVERSACION) is None
    assert store.get(tenant_id=_TENANT, draft_id="d-1").status is DraftStatus.EXPIRED  # type: ignore[union-attr]


def test_get_undoable_respeta_la_ventana() -> None:
    """Solo el `COMMITTED` con `undo_until` futuro se ofrece para deshacer."""
    store, reloj = _store()
    store.save(tenant_id=_TENANT, draft=_draft(status=DraftStatus.CONFIRMED))
    store.save(
        tenant_id=_TENANT,
        draft=_draft(
            status=DraftStatus.COMMITTED,
            undo_until=_AHORA + timedelta(minutes=10),
        ),
    )
    assert store.get_undoable(tenant_id=_TENANT, conversation_id=_CONVERSACION) is not None
    reloj.avanzar(timedelta(minutes=11))
    assert store.get_undoable(tenant_id=_TENANT, conversation_id=_CONVERSACION) is None


def test_find_by_correlation_id_con_aislamiento() -> None:
    """La idempotencia por `correlation_id` también respeta el comercio."""
    store, _ = _store()
    store.save(tenant_id=_TENANT, draft=_draft(correlation_id="corr-7"))
    assert store.find_by_correlation_id(tenant_id=_TENANT, correlation_id="corr-7") is not None
    assert store.find_by_correlation_id(tenant_id=_OTRO_TENANT, correlation_id="corr-7") is None


def test_cancelar_libera_la_ranura_activa() -> None:
    """Al cancelar el draft activo, la conversación queda sin draft activo."""
    store, _ = _store()
    store.save(tenant_id=_TENANT, draft=_draft(status=DraftStatus.AWAITING_CONFIRMATION))
    store.save(tenant_id=_TENANT, draft=_draft(status=DraftStatus.CANCELLED))
    assert store.get_active(tenant_id=_TENANT, conversation_id=_CONVERSACION) is None
