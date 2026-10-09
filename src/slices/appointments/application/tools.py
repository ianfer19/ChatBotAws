"""Las tools del agente de citas, sobre puertos inyectados (Paso 5: propose/commit).

Ninguna tool acepta el comercio del LLM: el `tenant_id` siempre llega del estado del
turno (contexto resuelto en el gateway), igual que en los ports. Las tools de
escritura (`propose_appointment`, `cancel_appointment`) no escriben datos reales:
crean un `PendingDraft`, aplican la política de riesgo determinista del dominio y solo
el commit (aquí mismo, para `AUTO`; el router del supervisor, para `CONFIRM`) materializa
la cita — ADR 0011. La disponibilidad se calcula del repositorio y del horario
inyectado; el modelo solo redacta.

`TODO(decision)`: convención de zona horaria (fechas locales naive vs UTC) al conectar
Aurora en el Paso 6, para que reloj, huecos y citas compartan criterio.
"""

import uuid
from collections.abc import Sequence
from datetime import date as Date
from datetime import datetime
from datetime import time as Time

from shared.contracts.pending import (
    ConfirmationPolicy,
    DraftStatus,
    PendingDraft,
    compute_payload_hash,
)
from shared.errors import ValidationError
from shared.ports import ClockPort, DraftStorePort
from slices.appointments.application.drafts import TTL_CONFIRMACION, commit_draft
from slices.appointments.application.schemas import (
    AppointmentView,
    OpeningHoursDay,
    Slot,
    ToolResult,
)
from slices.appointments.domain.entities import Appointment
from slices.appointments.domain.errors import (
    IncompleteAppointmentData,
    OutsideOpeningHours,
    SlotUnavailable,
    TenantMismatch,
)
from slices.appointments.domain.policy import decide_appointment, detect_inferred_fields
from slices.appointments.domain.ports import AppointmentRepositoryPort
from slices.appointments.domain.rules import (
    DURACION_CITA,
    missing_appointment_fields,
    overlapping_appointment,
    within_opening_hours,
)


def _require_tenant(tenant_id: str) -> None:
    """Rechaza operaciones sin comercio: ninguna tool trabaja «a ciegas».

    Args:
        tenant_id: Comercio resuelto en el gateway.

    Raises:
        ValidationError: Si `tenant_id` está vacío.
    """
    if not tenant_id:
        raise ValidationError("tenant_id vacío en las tools de citas")


def _vista(appointment: Appointment) -> AppointmentView:
    """Convierte una cita del dominio en la vista que consume el prompt de redacción.

    Args:
        appointment: Cita ya persistida.

    Returns:
        Vista inmutable con los campos seguros de mostrar.
    """
    return AppointmentView(
        id=appointment.id,
        starts_at=appointment.starts_at,
        customer_name=appointment.customer_name,
        status=appointment.status,
    )


def _es_comparable(ahora: datetime, momento: datetime) -> bool:
    """Indica si dos fechas se pueden comparar (ambas con o sin zona horaria).

    Args:
        ahora: Instante del reloj inyectado.
        momento: Instante generado por la tool.

    Returns:
        `True` si ambas son naive o ambas son aware; `False` en caso contrario.
    """
    return (ahora.tzinfo is None) == (momento.tzinfo is None)


def _resultado_existente(
    draft: PendingDraft, *, tenant_id: str, repo: AppointmentRepositoryPort, tool: str
) -> ToolResult:
    """Arma el resultado de una propuesta repetida (mismo `correlation_id`).

    Args:
        draft: Draft ya creado por la petición original.
        tenant_id: Comercio del turno.
        repo: Repositorio para recuperar la cita ya materializada (si hubo commit).
        tool: Tool que está siendo reintentada.

    Returns:
        `ToolResult` con el estado real del draft (idempotencia, sin duplicar nada).
    """
    decision = decide_appointment(inferred_fields=draft.inferred_fields)
    if tool == "propose_appointment":
        appointment = None
        if draft.status == DraftStatus.COMMITTED and draft.correlation_id:
            previa = repo.find_by_correlation_id(
                tenant_id=tenant_id, correlation_id=draft.correlation_id
            )
            if previa is not None:
                appointment = _vista(previa)
        return ToolResult(
            tool="propose_appointment",
            appointment=appointment,
            draft_id=draft.draft_id,
            draft_status=draft.status,
            policy=decision.policy,
            policy_reasons=decision.reasons,
        )
    cancelled_id = None
    if draft.status == DraftStatus.COMMITTED:
        previa = repo.find(
            tenant_id=tenant_id,
            appointment_id=str(draft.payload.get("appointment_id", "")),
        )
        if previa is not None:
            cancelled_id = previa.id
    return ToolResult(
        tool="cancel_appointment",
        cancelled_id=cancelled_id,
        draft_id=draft.draft_id,
        draft_status=draft.status,
        policy=decision.policy,
        policy_reasons=decision.reasons,
    )


class AppointmentTools:
    """Implementación de las cuatro tools contra repositorio, drafts y horario.

    Example:
        >>> from datetime import datetime
        >>> from adapters.in_memory import InMemoryDraftStore
        >>> from slices.appointments.infrastructure.in_memory import (
        ...     InMemoryAppointmentRepository,
        ... )
        >>> class _Reloj:
        ...     def now(self) -> datetime:
        ...         return datetime(2026, 3, 2, 8, 0)
        >>> reloj = _Reloj()
        >>> tools = AppointmentTools(
        ...     repo=InMemoryAppointmentRepository(),
        ...     clock=reloj,
        ...     opening_hours=[],
        ...     drafts=InMemoryDraftStore(clock=reloj),
        ... )
        >>> tools.get_opening_hours(tenant_id="Sede_Elite_01").hours
        []
    """

    def __init__(
        self,
        *,
        repo: AppointmentRepositoryPort,
        clock: ClockPort,
        opening_hours: Sequence[OpeningHoursDay],
        drafts: DraftStorePort,
    ) -> None:
        """Guarda los puertos con los que trabaja cada llamada.

        Args:
            repo: Repositorio de citas (en memoria hasta el Paso 6).
            clock: Reloj inyectable para ignorar huecos ya pasados.
            opening_hours: Horario de atención del comercio (falso hasta RAG/Paso 7).
            drafts: Store de propuestas pendientes (ADR 0011; DynamoDB en el Paso 6).
        """
        self._repo = repo
        self._clock = clock
        self._hours = tuple(opening_hours)
        self._drafts = drafts

    def get_availability(
        self, *, tenant_id: str, date: str, party_size: int | None = None
    ) -> ToolResult:
        """Huecos libres de un día: horario del comercio menos las citas existentes.

        Args:
            tenant_id: Comercio resuelto en el gateway.
            date: Día a consultar en ISO (`YYYY-MM-DD`).
            party_size: Aforo solicitado (`TODO(decision)`: aforo por mesa/habitación).

        Returns:
            `ToolResult` con los huecos libres, ya filtrados por pasado y ocupación.

        Raises:
            ValidationError: Si falta `tenant_id` o la fecha no es ISO válida.
        """
        _require_tenant(tenant_id)
        del party_size
        try:
            dia = Date.fromisoformat(date)
        except ValueError as exc:
            raise ValidationError(
                "fecha inválida en get_availability", details={"date": date}
            ) from exc

        aperturas = [h for h in self._hours if h.weekday == dia.weekday()]
        if not aperturas:
            return ToolResult(tool="get_availability", slots=[])

        ocupadas = self._repo.list_for_period(
            tenant_id=tenant_id,
            start=datetime.combine(dia, Time.min),
            end=datetime.combine(dia, Time.max),
        )
        ahora = self._clock.now()
        huecos: list[Slot] = []
        for bloque in aperturas:
            inicio = datetime.combine(dia, Time.fromisoformat(bloque.open_time))
            cierre = datetime.combine(dia, Time.fromisoformat(bloque.close_time))
            while inicio + DURACION_CITA <= cierre:
                fin = inicio + DURACION_CITA
                pasado = _es_comparable(ahora, inicio) and inicio <= ahora
                ocupado = any(inicio <= cita.starts_at < fin for cita in ocupadas)
                if not pasado and not ocupado:
                    huecos.append(Slot(start=inicio, end=fin))
                inicio = fin
        return ToolResult(tool="get_availability", slots=huecos)

    def propose_appointment(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        conversation_id: str,
        message: str,
        date: str,
        time: str,
        customer_name: str,
        contact: str,
    ) -> ToolResult:
        """Propone una cita como draft y aplica la política de riesgo (ADR 0011).

        Valida datos mínimos (reglas 4 y 5), turno (reglas 2 y 3) e idempotencia;
        después decide `AUTO` (commit inmediato con ventana de deshacer) o `CONFIRM`
        (draft `AWAITING_CONFIRMATION` que confirma el router del supervisor).

        Args:
            tenant_id: Comercio resuelto en el gateway.
            correlation_id: Clave de idempotencia: repetir la petición no duplica draft.
            conversation_id: Conversación dueña del draft (un solo activo por ella).
            message: Mensaje crudo del cliente (detecta campos inferidos).
            date: Fecha en ISO (`YYYY-MM-DD`).
            time: Hora (`HH:MM`).
            customer_name: Nombre del cliente.
            contact: Medio de contacto del cliente.

        Returns:
            `ToolResult` con la cita commiteada (`AUTO`) o solo el draft a la espera
            (`CONFIRM`), incluyendo `draft_id`, `draft_status` y `policy`.

        Raises:
            ValidationError: Si falta `tenant_id` o fecha/hora no son ISO válidas.
            IncompleteAppointmentData: Si falta alguno de los datos mínimos.
            SlotUnavailable: Si el turno ya pasó u ocupan otra cita (regla 2).
            OutsideOpeningHours: Si el turno cae fuera del horario (regla 3).
        """
        _require_tenant(tenant_id)
        faltantes = missing_appointment_fields(
            date=date, time=time, customer_name=customer_name, contact=contact
        )
        if faltantes:
            raise IncompleteAppointmentData(
                "faltan datos para proponer la cita",
                details={"faltan": ",".join(faltantes)},
            )

        previo = self._drafts.find_by_correlation_id(
            tenant_id=tenant_id, correlation_id=correlation_id
        )
        if previo is not None:
            return _resultado_existente(
                previo, tenant_id=tenant_id, repo=self._repo, tool="propose_appointment"
            )

        inicio = self._parsear_inicio(date=date, time=time)
        self._exigir_turno_libre(tenant_id=tenant_id, inicio=inicio)

        inferidos = detect_inferred_fields(
            message=message,
            fields={
                "date": date,
                "time": time,
                "customer_name": customer_name,
                "contact": contact,
            },
        )
        decision = decide_appointment(inferred_fields=inferidos)
        payload = {
            "op": "create",
            "date": date,
            "time": time,
            "customer_name": customer_name,
            "contact": contact,
        }
        draft = self._nuevo_draft(
            payload=payload,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            inferred=inferidos,
        )
        self._drafts.save(tenant_id=tenant_id, draft=draft)
        if decision.policy is ConfirmationPolicy.AUTO:
            return self._commitear(
                draft.model_copy(update={"status": DraftStatus.AUTO_APPROVED}),
                tool="propose_appointment",
                tenant_id=tenant_id,
                decision_policy=decision.policy,
                reasons=decision.reasons,
            )
        pendiente = draft.model_copy(update={"status": DraftStatus.AWAITING_CONFIRMATION})
        self._drafts.save(tenant_id=tenant_id, draft=pendiente)
        return ToolResult(
            tool="propose_appointment",
            draft_id=pendiente.draft_id,
            draft_status=pendiente.status,
            policy=decision.policy,
            policy_reasons=decision.reasons,
        )

    def cancel_appointment(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        conversation_id: str,
        message: str,
        appointment_id: str,
    ) -> ToolResult:
        """Propone cancelar una cita existente de este comercio (reglas 1 y 6).

        Igual que `propose_appointment`, pero la escritura va como draft de `op` cancel:
        con el id literal en el mensaje la política puede ir a `AUTO` (con ventana de
        deshacer); si el modelo lo infirió, queda `AWAITING_CONFIRMATION`.

        Args:
            tenant_id: Comercio resuelto en el gateway.
            correlation_id: Clave de idempotencia de la propuesta.
            conversation_id: Conversación dueña del draft.
            message: Mensaje crudo del cliente (detecta campos inferidos).
            appointment_id: Cita a cancelar.

        Returns:
            `ToolResult` con `cancelled_id` si ya se ejecutó, o solo el draft si está
            a la espera de confirmación.

        Raises:
            ValidationError: Si falta `tenant_id` o el id está vacío.
            IncompleteAppointmentData: Si no se indicó qué cita cancelar.
            TenantMismatch: Si la cita no existe en este comercio (rechazo genérico).
        """
        _require_tenant(tenant_id)
        if not appointment_id:
            raise IncompleteAppointmentData(
                "falta la cita a cancelar",
                details={"faltan": "appointment_id"},
            )

        previo = self._drafts.find_by_correlation_id(
            tenant_id=tenant_id, correlation_id=correlation_id
        )
        if previo is not None:
            return _resultado_existente(
                previo, tenant_id=tenant_id, repo=self._repo, tool="cancel_appointment"
            )

        cita = self._repo.find(tenant_id=tenant_id, appointment_id=appointment_id)
        if cita is None:
            raise TenantMismatch(
                "cita no encontrada en este comercio",
                details={"appointment_id": appointment_id},
            )
        if cita.status == "cancelled":
            return ToolResult(tool="cancel_appointment", cancelled_id=cita.id)

        inferidos = detect_inferred_fields(
            message=message, fields={"appointment_id": appointment_id}
        )
        decision = decide_appointment(inferred_fields=inferidos)
        draft = self._nuevo_draft(
            payload={"op": "cancel", "appointment_id": appointment_id},
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            inferred=inferidos,
        )
        self._drafts.save(tenant_id=tenant_id, draft=draft)
        if decision.policy is ConfirmationPolicy.AUTO:
            return self._commitear(
                draft.model_copy(update={"status": DraftStatus.AUTO_APPROVED}),
                tool="cancel_appointment",
                tenant_id=tenant_id,
                decision_policy=decision.policy,
                reasons=decision.reasons,
            )
        pendiente = draft.model_copy(update={"status": DraftStatus.AWAITING_CONFIRMATION})
        self._drafts.save(tenant_id=tenant_id, draft=pendiente)
        return ToolResult(
            tool="cancel_appointment",
            draft_id=pendiente.draft_id,
            draft_status=pendiente.status,
            policy=decision.policy,
            policy_reasons=decision.reasons,
        )

    def get_opening_hours(self, *, tenant_id: str) -> ToolResult:
        """Horario de atención del comercio (regla 7: sale de la tool, nunca del LLM).

        Args:
            tenant_id: Comercio resuelto en el gateway.

        Returns:
            `ToolResult` con los días y franjas inyectados en la construcción.

        Raises:
            ValidationError: Si falta `tenant_id`.
        """
        _require_tenant(tenant_id)
        return ToolResult(tool="get_opening_hours", hours=list(self._hours))

    def _parsear_inicio(self, *, date: str, time: str) -> datetime:
        """Convierte fecha y hora ISO en el inicio de la cita propuesto.

        Args:
            date: Fecha en ISO (`YYYY-MM-DD`).
            time: Hora (`HH:MM`).

        Returns:
            El inicio como `datetime` naive local.

        Raises:
            ValidationError: Si fecha u hora no son ISO válidas.
        """
        try:
            return datetime.fromisoformat(f"{date}T{time}")
        except ValueError as exc:
            raise ValidationError(
                "fecha u hora inválidas en propose_appointment",
                details={"date": date, "time": time},
            ) from exc

    def _exigir_turno_libre(self, *, tenant_id: str, inicio: datetime) -> None:
        """Aplica las reglas 2 y 3 al turno propuesto antes de crear el draft.

        Args:
            tenant_id: Comercio dueño del calendario.
            inicio: Inicio propuesto para la cita.

        Raises:
            SlotUnavailable: Si el turno ya pasó o lo ocupa otra cita (regla 2).
            OutsideOpeningHours: Si el turno no cabe en el horario (regla 3).
        """
        ahora = self._clock.now()
        if _es_comparable(ahora, inicio) and inicio <= ahora:
            raise SlotUnavailable(
                "el turno propuesto ya pasó",
                details={"inicio": inicio.isoformat(), "motivo": "pasado"},
            )
        if not within_opening_hours(start=inicio, opening_hours=self._hours):
            raise OutsideOpeningHours(
                "el turno está fuera del horario de atención",
                details={"inicio": inicio.isoformat()},
            )
        dia = inicio.date()
        ocupadas = self._repo.list_for_period(
            tenant_id=tenant_id,
            start=datetime.combine(dia, Time.min),
            end=datetime.combine(dia, Time.max),
        )
        choque = overlapping_appointment(start=inicio, existing=ocupadas)
        if choque is not None:
            raise SlotUnavailable(
                "el turno ya está ocupado",
                details={
                    "inicio": inicio.isoformat(),
                    "ocupada_inicio": choque.starts_at.isoformat(),
                },
            )

    def _nuevo_draft(
        self,
        *,
        payload: dict[str, str],
        tenant_id: str,
        conversation_id: str,
        correlation_id: str,
        inferred: tuple[str, ...],
    ) -> PendingDraft:
        """Arma el draft recién propuesto (estado inicial `DRAFTED`).

        Args:
            payload: Contenido exacto propuesto (se hashea al construirlo).
            tenant_id: Comercio dueño del draft.
            conversation_id: Conversación a la que pertenece.
            correlation_id: Idempotencia de la propuesta.
            inferred: Campos inferidos por el LLM (disparan `CONFIRM`).

        Returns:
            El draft listo para guardarse.
        """
        ahora = self._clock.now()
        return PendingDraft(
            draft_id=f"drf-{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            kind="appointment",
            status=DraftStatus.DRAFTED,
            payload={**payload},
            inferred_fields=inferred,
            total=0.0,
            payload_hash=compute_payload_hash({**payload}),
            correlation_id=correlation_id,
            created_at=ahora,
            expires_at=ahora + TTL_CONFIRMACION,
        )

    def _commitear(
        self,
        draft: PendingDraft,
        *,
        tool: str,
        tenant_id: str,
        decision_policy: ConfirmationPolicy,
        reasons: tuple[str, ...],
    ) -> ToolResult:
        """Marca el draft `AUTO_APPROVED`, lo commitea y arma el resultado.

        Args:
            draft: Draft propuesto (se guarda en `AUTO_APPROVED` antes del commit).
            tool: Tool que produjo la propuesta.
            tenant_id: Comercio dueño del draft.
            decision_policy: Política aplicada (siempre `AUTO` en esta ruta).
            reasons: Motivos de la política para logs y tests.

        Returns:
            `ToolResult` con la cita/`cancelled_id` ya materializados.

        Raises:
            DraftNotFound: Si el draft desaparece entre guardar y commitear (no debe).
            DraftNotCommittable: Si un estado intermedio rompe la máquina (no debe).
        """
        self._drafts.save(tenant_id=tenant_id, draft=draft)
        appointment = commit_draft(
            tenant_id=tenant_id,
            draft_id=draft.draft_id,
            repo=self._repo,
            drafts=self._drafts,
            clock=self._clock,
        )
        if tool == "propose_appointment":
            return ToolResult(
                tool="propose_appointment",
                appointment=_vista(appointment),
                draft_id=draft.draft_id,
                draft_status=DraftStatus.COMMITTED,
                policy=decision_policy,
                policy_reasons=reasons,
            )
        return ToolResult(
            tool="cancel_appointment",
            cancelled_id=appointment.id,
            draft_id=draft.draft_id,
            draft_status=DraftStatus.COMMITTED,
            policy=decision_policy,
            policy_reasons=reasons,
        )
