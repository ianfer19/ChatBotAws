# Slice: appointments

> Paso de implementación: **Pasos 3 y 5**. Estado: **Paso 3 hecho** (grafo, `AgentState`,
> tools) y **Paso 5 completo (Fases 1–5)**: propose/commit con política de riesgo, reglas
> 2 y 3, estados canónicos, drafts, `Deps.allowed_tools` con intersección en
> `select_action`, evals y contratos. Pendiente en la ruta: adapter legacy (Paso 11).

## Responsabilidad
Reservas y citas de los comercios: consultar disponibilidad, proponer y cancelar citas y
exponer los horarios de atención. No decide la intención (eso lo hace `supervisor`), no
almacena el conocimiento general (eso es `knowledge_rag`) y no recibe el mensaje del
canal (eso es `conversation_gateway`).

## Entradas y salidas
- Entradas: llamadas a las tools del especialista de citas (`get_availability`,
  `propose_appointment`, `cancel_appointment`, `get_opening_hours`) con el contexto ya
  resuelto (`tenant_id`, `correlation_id`, `conversation_id`) entregado por
  `shared/context` y con el `message` crudo del cliente (la política detecta campos
  inferidos).
- Salidas: `ToolResult` con la cita/`cancelled_id` ya materializados o solo el draft
  (`draft_id`, `draft_status`, `policy`); logs de auditoría con `correlation_id` y
  `tenant_id`.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): contratos de disponibilidad y
  citas (TODO(decision): nombres finales de los contratos).
- Consume: `AppointmentRepositoryPort`, `ClockPort` y `LegacyOpsPort` (Protocol en
  `domain/ports.py` — endpoints del catálogo/ops del legacy, **sin HTTP hasta el Paso 11**,
  `TODO(verify)`), `DraftStorePort` de `shared/ports/` (implementación hoy
  `adapters/in_memory.InMemoryDraftStore`; DynamoDB `pending_actions` en el Paso 6) y
  `adapters/bedrock` (solo redacción).
- Definidos en el **Paso 1**: `domain/entities.py` (`Appointment`, `AppointmentStatus =
  Literal["pending", "confirmed", "cancelled"]`), `domain/ports.py`
  (`AppointmentRepositoryPort`), `infrastructure/in_memory.py`
  (`InMemoryAppointmentRepository`).
- Definidos en el **Paso 3**: `domain/rules.py` (datos mínimos), `domain/errors.py`
  (`IncompleteAppointmentData`, `TenantMismatch`) y `application/` (`state.py`,
  `schemas.py`, `prompts.py`, `tools.py`, `deps.py`, `nodes/`, `graph.py`).
- Definidos en la **Fase 2 del Paso 5**: `domain/hours.py` (`OpeningHoursDay`),
  `domain/rules.py` (`DURACION_CITA`, `overlapping_appointment`,
  `within_opening_hours`), `domain/policy.py` (`detect_inferred_fields`,
  `decide_appointment`), errores `SlotUnavailable`/`OutsideOpeningHours`/`DraftNotFound`/
  `DraftNotCommittable` y `application/drafts.py` (`commit_draft`, `confirm_draft`,
  `cancel_draft`, `undo_draft`, `TTL_CONFIRMACION`, `VENTANA_DESHACER`).

## Grafo (Pasos 3 y 5)
- `application/graph.py` → `build_appointment_graph(llm, repo, clock, opening_hours,
  drafts, allowed_tools=None)`. Nodos en `application/nodes/`: `understand` (LLM → JSON validado en
  `AppointmentProposal`, con reintento único y degradación a aclaración; el `system`
  incluye «hoy es `YYYY-MM-DD` (día)» con el `ClockPort`), `validate` + `need_more?`
  (regla 4), `select_action` (allowlist `ALLOWED_TOOLS` intersecada con
  `Deps.allowed_tools` — mínimo privilegio por comercio; sin `tool_name` si no aplica),
  `call_tool` (despacho con `conversation_id`/`message`; un `AppError` de la tool se
  traduce en `tool_error` y se loguea `draft_id`/`draft_status`/`policy`),
  `validate_result` + `needs_confirmation?` (coherencia del resultado; la confirmación
  sale del `draft_status`, nunca de una lista fija) y `respond` (redacción: espera
  confirmación si el draft está `AWAITING_CONFIRMATION`, entrega si `COMMITTED`).
- `AgentState` (`application/state.py`): el llamador pone `tenant_id`, `correlation_id`,
  `conversation_id`, `user_message` y `history`; el resto lo escriben los nodos
  (`NotRequired`). `conversation_id` es **requerido**: es la ranura única de drafts
  (compuesto `canal:customer_id` en `supervisor/route_appointments` hasta el Paso 9,
  `TODO(verify)`).
- Dos llamadas al LLM por turno (interpretar y redactar). **Sin checkpointer**
  (`TODO(decision)`: multi-turno con checkpointer en el Paso 8).
- Confirmación (ADR 0011): ninguna tool escribe datos reales directamente. Las tools de
  escritura crean un `PendingDraft`, el dominio decide `AUTO` (commit inmediato con
  `VENTANA_DESHACER` de 30 min) o `CONFIRM` (draft `AWAITING_CONFIRMATION` que confirma
  el router `resolve_pending` del supervisor con `ConfirmerPort`, Fase 4);
  `confirm_draft` exige el `payload_hash`.

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| Aurora PostgreSQL (tabla `appointments`) | Historial y estado de las citas creadas | 6 |
| DynamoDB `pending_actions` (TTL 24 h, `ConditionExpression` de commit) | Drafts propose/commit (`DraftStorePort`) | 6 |
| DynamoDB `appointment_locks` (TTL corto) | Idempotencia por `correlation_id` | 6 |
| APIs legacy `ops_service` vía AgentCore Gateway + Policy | Disponibilidad y creación reales (`LegacyOpsPort` hoy sin HTTP) | 11 |
| CloudWatch Logs | Auditoría de cada invocación de tool | 5 |

## Reglas de negocio clave
1. Todo dato se filtra por el `tenant_id` resuelto en el gateway: jamás se consulta o
   crea una cita de otro comercio aunque el LLM lo pida.
2. No solapes: dos citas del mismo comercio no ocupan el mismo turno (`cancelled` no
   ocupa; `SlotUnavailable` con el choque en los detalles).
3. Toda cita cae entera dentro del horario de atención del comercio; un día sin franja
   nunca está dentro (`OutsideOpeningHours`; festivos: TODO(decision)).
4. Confirmación humana obligatoria: si faltan fecha, hora o datos del cliente, el bot
   pide la información y NO crea la cita.
5. Datos mínimos para crear: fecha, hora, nombre y medio de contacto del cliente.
6. `cancel_appointment` solo sobre citas existentes, del mismo tenant y no ya cancelada
   (cancelar dos veces es idempotente sin draft nuevo).
7. La disponibilidad y los horarios nunca los inventa el LLM: salen de la tool o del
   backend.
8. **Política de riesgo (ADR 0011.3)**: si algún campo obligatorio fue inferido por el
   modelo (heurística `detect_inferred_fields`: valor literal ausente, o indicadores de
   fecha/hora relativos), la propuesta va `CONFIRM` con motivos `campo_inferido:<campo>`;
   si todo lo dijo el cliente, `AUTO` con ventana de deshacer. Nada depende solo del prompt.

## Tools expuestas al LLM
| Tool | Esquema resumido | Notas de seguridad |
|---|---|---|
| `get_availability` | `{date, party_size?}` → `[slot]` | Solo lectura; filtra por el tenant del contexto |
| `propose_appointment` | `{date, time, customer_name, contact, message, conversation_id}` → cita o draft | Escribe **solo** como draft; política `AUTO`/`CONFIRM`; idempotente por `correlation_id`; valida datos mínimos, pasado, horario y solape |
| `cancel_appointment` | `{appointment_id, message, conversation_id}` → `cancelled_id` o draft | Misma mecánica draft; autoriza por tenant y estado; ventana de deshacer |
| `get_opening_hours` | `{}` → horarios | Si procede del conocimiento, delega en RAG con `tenant_id` |

Ninguna tool acepta `tenant_id` en el payload: siempre es argumento del contexto (hay un
test de contrato que falla si aparece `**kwargs` o campos de más).

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `SlotUnavailable` | El turno ya pasó u ocupa otra cita | "Ese horario ya no está disponible" + log warn (`motivo: pasado` o `ocupada_inicio`) |
| `OutsideOpeningHours` | Turno fuera del horario (regla 3) | Sugerir un turno válido + log warn |
| `IncompleteAppointmentData` | Faltan datos mínimos | El bot pide los datos; no se crea nada + log info |
| `TenantMismatch` | Cita inexistente en este comercio | Rechazo genérico sin detalles + log error |
| `DraftNotFound` | No hay draft con ese id en el comercio | "La propuesta ya no está disponible" + log warn |
| `DraftNotCommittable` | Transición ilegal (commit desde `DRAFTED`, undo fuera de ventana…) | "La propuesta ya no admite cambios" + log warn |
| `LegacyTimeout` | `ops_service` no responde (Paso 11) | Disculpa al usuario + log error con `correlation_id` (`TODO(decision)`) |

Los errores de tool llegan a `respond` como `tool_error` (`code` + mensaje interno): el
turno nunca se rompe por un fallo de negocio.

## Cómo probarlo
- `tests/unit/` (Paso 1, hecho): `test_appointments_repository.py` — el doble cumple el
  port, aislamiento por tenant, idempotencia por `correlation_id`, periodo de consulta y
  entidad inmutable.
- `tests/unit/` (Paso 3, hecho): `test_appointments_graph.py` — nodos sueltos, allowlist
  sincronizada con `ToolName` y end-to-end (saludo, propuesta a la espera, `AUTO` con
  literales, disponibilidad y el negativo: JSON con `tenant_id` ajeno no ejecuta nada).
- `tests/unit/` (Fase 2 del Paso 5, hecho): `test_appointments_rules.py` (datos mínimos,
  solapes, horario), `test_appointments_policy.py` (detección de inferidos y política),
  `test_appointments_tools.py` (propose/commit, idempotencia, solape, horario, pasado,
  cancel) y `test_appointments_drafts.py` (ciclo de vida: confirm con hash, commit,
  cancel, undo dentro/fuera de ventana).
- `tests/contract/` (Fase 2, hecho): `test_appointments_tools_contract.py` — la
  propuesta rechaza `tenant_id` y claves de más, el `ToolResult` es inmutable y las tools
  de escritura solo admiten argumentos nombrados y anotados.
- Fase 4 (hecho): tool deshabilitada en `tests/unit/test_appointments_graph.py`
  (`test_select_action_recorta_las_tools_por_el_comercio` y
  `test_e2e_tool_fuera_del_entitlement_no_ejecuta_ni_se_inventa`).
- Fase 5 (hecho): `tests/agent_evals/datasets/appointments_behavior.json` con su ejecutor
  `tests/agent_evals/test_appointments_dataset.py` («quiero una cita el viernes» sin hora
  → pide el dato y no crea nada, `appt_sin_hora_01`; hora inferida → confirmación,
  `appt_hora_inferida_01`; acción inexistente de hora → degradación honesta,
  `appt_time_01`) y contrato de `PendingDraft` en
  `tests/contract/test_pending_contracts.py`.
- Manual contra Bedrock (hecho el 2026-10-08 y re-ejecutado el 2026-10-09 en la Fase 5,
  cuenta `iastock-old`): REPL `python scripts\chat_citas.py` (comandos `/status`,
  `/reset`, `--turno`, `--debug`; ahora con `orders_graph`, `confirmer` y `draft_store`
  cableados) y smokes `pytest tests/integration -rs` (`5 passed`, incluye
  `test_supervisor_enruta_un_pedido_al_especialista`).
