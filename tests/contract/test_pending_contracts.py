"""Contrato de los drafts de confirmación y de la vista de pedido (Paso 5, Fase 5).

Frontera compartida entre el `supervisor` (router de confirmación) y los
especialistas: `PendingDraft` del kernel y `OrderView`/`OrderProposal` de `orders`.
Lo que se verifica aquí no puede romperse sin avisar a los consumidores (AGENTS.md
raíz, §9): inmutabilidad, `extra="forbid"`, hash canónico y ausencia total de campos
de hora o de tenant en la vista (defensa en profundidad de la regla crítica, §7).
"""

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError as SchemaValidationError

from shared.contracts.pending import PendingDraft, compute_payload_hash
from slices.orders.application.schemas import OrderProposal, OrderView
from slices.orders.domain.entities import OrderItem

pytestmark = pytest.mark.contract

_AHORA = datetime(2026, 3, 2, 12, 0)
_PAYLOAD: dict[str, Any] = {"op": "create", "items": [{"sku": "A-100", "quantity": 2}]}
_HASH = compute_payload_hash(_PAYLOAD)
_CLAVES_DE_HORA = ("scheduled_at", "scheduled_time", "hora", "date", "time")


def _draft(sobrescribir: dict[str, Any] | None = None) -> PendingDraft:
    """Draft mínimo válido para los tests de contrato.

    Args:
        sobrescribir: Campos a reemplazar (para probar validación).

    Returns:
        El draft ya validado.
    """
    campos: dict[str, Any] = {
        "draft_id": "drf-1",
        "tenant_id": "Sede_Elite_01",
        "conversation_id": "whatsapp:57300111111",
        "kind": "order",
        "payload": dict(_PAYLOAD),
        "payload_hash": _HASH,
        "created_at": _AHORA,
        "expires_at": _AHORA,
    }
    campos.update(sobrescribir or {})
    return PendingDraft.model_validate(campos)


def test_pending_draft_es_inmutable_y_sin_claves_ajenas() -> None:
    """El draft no admite cambios laterales ni claves fuera del esquema."""
    draft = _draft()
    with pytest.raises(SchemaValidationError):
        draft.payload_hash = "hash-ajeno"  # pyrefly: ignore[read-only]
    with pytest.raises(SchemaValidationError):
        _draft({"scheduled_at": "2026-03-02T15:00"})


def test_pending_draft_exige_tenant_conversacion_y_hash() -> None:
    """Los identificadores del dueño y el hash son obligatorios y no vacíos."""
    with pytest.raises(SchemaValidationError):
        _draft({"tenant_id": ""})
    with pytest.raises(SchemaValidationError):
        _draft({"conversation_id": ""})
    with pytest.raises(SchemaValidationError):
        _draft({"payload_hash": ""})


def test_pending_draft_no_tiene_campos_de_hora() -> None:
    """La ventana del draft usa solo `created_at`/`expires_at`/`undo_until`: nada de hora."""
    assert not set(_CLAVES_DE_HORA) & set(PendingDraft.model_fields)


def test_el_hash_canonico_enlaza_al_payload_exacto() -> None:
    """El mismo contenido da siempre el mismo hash y cualquier cambio lo rompe."""
    igual = {"items": [{"sku": "A-100", "quantity": 2}], "op": "create"}
    assert compute_payload_hash(igual) == _HASH
    distinto = {"op": "create", "items": [{"sku": "A-100", "quantity": 3}]}
    assert compute_payload_hash(distinto) != _HASH


def test_order_view_es_inmutable_y_sin_hora_ni_tenant() -> None:
    """La vista lleva solo lo redactable: sin hora, sin tenant y sin mutaciones."""
    vista = OrderView(id="ord-1", status="ABIERTA", total=41_000)
    with pytest.raises(SchemaValidationError):
        vista.total = 0.0  # pyrefly: ignore[read-only]
    with pytest.raises(SchemaValidationError):
        OrderView.model_validate(
            {"id": "ord-1", "status": "ABIERTA", "total": 41_000, "scheduled_at": "15:00"}
        )
    with pytest.raises(SchemaValidationError):
        OrderView.model_validate(
            {"id": "ord-1", "status": "ABIERTA", "total": 41_000, "tenant_id": "Ajeno"}
        )
    assert not set(_CLAVES_DE_HORA) & set(OrderView.model_fields)
    assert "tenant_id" not in OrderView.model_fields


def test_order_proposal_es_inmutable() -> None:
    """La propuesta validada no se puede reescribir después de `understand`."""
    propuesta = OrderProposal(action="propose_order", items=(OrderItem(sku="A-100", quantity=2),))
    with pytest.raises(SchemaValidationError):
        propuesta.action = "reply"  # pyrefly: ignore[read-only]
