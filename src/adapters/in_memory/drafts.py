"""`DraftStorePort` en memoria: doble de tests y desarrollo previo a DynamoDB (Paso 6).

Mismo papel que los demás `infrastructure/in_memory.py`: probar las invariantes del
ADR 0011 sin tocar infraestructura. La implementación real (`pending_actions` con TTL
y `ConditionExpression` de commit) llega en el Paso 6 tras `adapters/dynamodb/`.
"""

from shared.contracts.pending import (
    COMMITIBLE_STATUSES,
    DraftStatus,
    PendingDraft,
    compute_payload_hash,
)
from shared.errors import ValidationError
from shared.ports import ClockPort


def _require_tenant(tenant_id: str) -> None:
    """Rechaza operaciones sin comercio: ningún método trabaja «a ciegas».

    Args:
        tenant_id: Comercio resuelto en el gateway.

    Raises:
        ValidationError: Si `tenant_id` está vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en el store de drafts")


class InMemoryDraftStore:
    """`DraftStorePort` sobre diccionarios de proceso único, con reloj inyectado.

    Invariantes que exige (las mismas que después impone DynamoDB):
    integridad `payload_hash` ↔ `payload`, un solo draft activo por conversación y
    `COMMITTED` solo desde `AUTO_APPROVED`/`CONFIRMED`.

    Example:
        >>> from datetime import datetime
        >>> class _Reloj:
        ...     def now(self) -> datetime:
        ...         return datetime(2026, 3, 2, 8, 0)
        >>> store = InMemoryDraftStore(clock=_Reloj())
        >>> store.get_active(tenant_id="Sede_Elite_01", conversation_id="c1") is None
        True
    """

    def __init__(self, *, clock: ClockPort) -> None:
        """Guarda el reloj con el que se evalúan TTL y ventana de deshacer.

        Args:
            clock: Reloj inyectable (fijo en tests).
        """
        self._clock = clock
        self._drafts: dict[tuple[str, str], PendingDraft] = {}
        self._activos: dict[tuple[str, str], str] = {}
        self._correlaciones: dict[tuple[str, str], str] = {}

    def save(self, *, tenant_id: str, draft: PendingDraft) -> None:
        """Guarda o actualiza el draft validando las tres invariantes del ADR 0011.

        Args:
            tenant_id: Comercio bajo el que se guarda.
            draft: Draft a persistir.

        Raises:
            ValidationError: Si falta `tenant_id`, el draft es de otro comercio, el
                `payload_hash` no corresponde al `payload`, o el `COMMITTED` no viene
                de un estado `COMMITIBLE`.
        """
        _require_tenant(tenant_id)
        if draft.tenant_id != tenant_id:
            raise ValidationError(
                "el draft pertenece a otro comercio",
                details={"tenant_solicitado": tenant_id, "tenant_draft": draft.tenant_id},
            )
        if compute_payload_hash(draft.payload) != draft.payload_hash:
            raise ValidationError(
                "payload_hash no corresponde al payload del draft",
                details={"draft_id": draft.draft_id},
            )

        clave = (tenant_id, draft.draft_id)
        previo = self._drafts.get(clave)
        if draft.status == DraftStatus.COMMITTED and (
            previo is None or previo.status not in COMMITIBLE_STATUSES
        ):
            raise ValidationError(
                "commit ilegal: solo desde AUTO_APPROVED o CONFIRMED",
                details={
                    "draft_id": draft.draft_id,
                    "estado_previo": previo.status if previo else "inexistente",
                },
            )

        conv = (tenant_id, draft.conversation_id)
        activo_previo = self._activos.get(conv)
        if draft.is_active():
            if activo_previo is not None and activo_previo != draft.draft_id:
                anterior = self._drafts[(tenant_id, activo_previo)]
                self._drafts[(tenant_id, activo_previo)] = anterior.model_copy(
                    update={"status": DraftStatus.SUPERSEDED}
                )
            self._activos[conv] = draft.draft_id
        elif self._activos.get(conv) == draft.draft_id:
            del self._activos[conv]

        self._drafts[clave] = draft
        if draft.correlation_id:
            self._correlaciones.setdefault((tenant_id, draft.correlation_id), draft.draft_id)

    def get(self, *, tenant_id: str, draft_id: str) -> PendingDraft | None:
        """Devuelve el draft del tenant indicado o `None` si no existe.

        Args:
            tenant_id: Comercio cuyos drafts se consultan.
            draft_id: Identificador del draft.

        Returns:
            El draft o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return self._drafts.get((tenant_id, draft_id))

    def get_active(self, *, tenant_id: str, conversation_id: str) -> PendingDraft | None:
        """Devuelve el único draft activo vigente; expira perezosamente los caducados.

        Args:
            tenant_id: Comercio cuya conversación se consulta.
            conversation_id: Conversación a consultar.

        Returns:
            El draft activo o `None`; un draft activo con `expires_at` pasado se marca
            `EXPIRED`, deja la ranura activa libre y se devuelve `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        conv = (tenant_id, conversation_id)
        draft_id = self._activos.get(conv)
        if draft_id is None:
            return None
        draft = self._drafts[(tenant_id, draft_id)]
        if draft.expires_at <= self._clock.now():
            self.save(
                tenant_id=tenant_id,
                draft=draft.model_copy(update={"status": DraftStatus.EXPIRED}),
            )
            return None
        return draft

    def get_undoable(self, *, tenant_id: str, conversation_id: str) -> PendingDraft | None:
        """Devuelve el draft `COMMITTED` cuya ventana de deshacer sigue abierta.

        Args:
            tenant_id: Comercio cuya conversación se consulta.
            conversation_id: Conversación a consultar.

        Returns:
            El draft deshacible o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        ahora = self._clock.now()
        for (stored_tenant, _), draft in self._drafts.items():
            if (
                stored_tenant == tenant_id
                and draft.conversation_id == conversation_id
                and draft.status == DraftStatus.COMMITTED
                and draft.undo_until is not None
                and draft.undo_until > ahora
            ):
                return draft
        return None

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> PendingDraft | None:
        """Devuelve el draft propuesto por esa petición o `None`.

        Args:
            tenant_id: Comercio cuyos drafts se consultan.
            correlation_id: `correlation_id` de la propuesta original.

        Returns:
            El draft o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        draft_id = self._correlaciones.get((tenant_id, correlation_id))
        if draft_id is None:
            return None
        return self._drafts.get((tenant_id, draft_id))
