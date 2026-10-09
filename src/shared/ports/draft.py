"""Puerto de persistencia de drafts de acción pendiente (ADR 0011).

Vive en el kernel porque lo consumen `supervisor` (router de confirmación) y los
especialistas (propose/commit); la implementación concreta está en
`adapters/in_memory/` (Paso 5) y en `adapters/dynamodb/` (Paso 6, tabla
`pending_actions` con TTL). El store exige las invariantes del ADR: integridad del
`payload_hash`, un solo draft activo por conversación y commit solo desde
`AUTO_APPROVED`/`CONFIRMED`.
"""

from typing import Protocol, runtime_checkable

from shared.contracts.pending import PendingDraft


@runtime_checkable
class DraftStorePort(Protocol):
    """Almacenamiento de drafts, siempre limitado a un comercio."""

    def save(self, *, tenant_id: str, draft: PendingDraft) -> None:
        """Guarda o actualiza el draft, validando las invariantes del ADR 0011.

        Al guardar un draft activo que reemplaza a otro activo de la misma
        conversación, el anterior queda persistido como `SUPERSEDED`.

        Args:
            tenant_id: Comercio bajo el que se guarda; debe coincidir con el del draft.
            draft: Draft a persistir (payload ya hasheado).

        Raises:
            ValidationError: Si falta `tenant_id`, si `payload_hash` no coincide con
                el `payload`, o si se intenta un `COMMITTED` que no viene de
                `AUTO_APPROVED`/`CONFIRMED` (o no viene de ningún draft).
        """
        ...

    def get(self, *, tenant_id: str, draft_id: str) -> PendingDraft | None:
        """Busca un draft por su identificador dentro del comercio indicado.

        Args:
            tenant_id: Comercio cuyos drafts se consultan.
            draft_id: Identificador del draft.

        Returns:
            El draft si existe y pertenece a `tenant_id`; `None` en cualquier otro
            caso (un draft ajeno se reporta como inexistente, nunca como ajeno).

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def get_active(self, *, tenant_id: str, conversation_id: str) -> PendingDraft | None:
        """Devuelve el único draft activo de la conversación, si lo hay.

        Los drafts activos cuyo `expires_at` ya pasó se marcan `EXPIRED` y dejan de
        estar activos (expiración perezosa; DynamoDB usará TTL nativo en el Paso 6).

        Args:
            tenant_id: Comercio cuya conversación se consulta.
            conversation_id: Conversación a consultar.

        Returns:
            El draft activo vigente o `None` si no hay ninguno.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def get_undoable(self, *, tenant_id: str, conversation_id: str) -> PendingDraft | None:
        """Devuelve el draft recién commiteado que aún admite deshacer.

        Args:
            tenant_id: Comercio cuya conversación se consulta.
            conversation_id: Conversación a consultar.

        Returns:
            El draft `COMMITTED` con `undo_until` futuro o `None`.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...

    def find_by_correlation_id(self, *, tenant_id: str, correlation_id: str) -> PendingDraft | None:
        """Recupera el draft propuesto por una petición anterior (idempotencia).

        Args:
            tenant_id: Comercio cuyos drafts se consultan.
            correlation_id: `correlation_id` de la propuesta original.

        Returns:
            El draft ya creado para esa petición o `None` si no existe.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        ...
