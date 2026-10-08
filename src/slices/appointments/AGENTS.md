# Slice: appointments

> Paso de implementación: **Pasos 3 y 5**. Estado: **Paso 3 hecho** — grafo de citas,
> `AgentState` y las 4 tools sobre dobles en memoria; **Paso 5 pendiente** — solapes,
> horario, estados canónicos y confirmación previa real.

## Responsabilidad
Reservas y citas de los comercios: consultar disponibilidad, crear y cancelar citas y
exponer los horarios de atención. No decide la intención (eso lo hace `supervisor`), no
almacena el conocimiento general (eso es `knowledge_rag`) y no recibe el mensaje del
canal (eso es `conversation_gateway`).

## Entradas y salidas
- Entradas: llamadas a las tools del especialista de citas (`get_availability`,
  `create_appointment`, `cancel_appointment`, `get_opening_hours`) con el contexto ya
  resuelto (`tenant_id`, `correlation_id`) entregado por `shared/context`.
- Salidas: contratos de disponibilidad y citas en `../../../shared/contracts/`; llamadas
  al backend legacy (`ops_service`) vía `adapters/legacy_backend`; logs de auditoría
  con `correlation_id` y `tenant_id`.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): `AvailabilityQuery` /
  `AvailabilitySlot`, `AppointmentCreate`, `AppointmentCancel` y `AppointmentView`
  (TODO(decision): nombres finales de los contratos).
- Consume: `VectorStorePort` (horarios del comercio en Aurora; adapter
  `adapters/aurora`), ports del propio domain (`LegacyOpsPort`,
  `AppointmentRepositoryPort`, `ClockPort`) y los adapters `adapters/legacy_backend`
  (disponibilidad y creación reales) y `adapters/bedrock` (solo redacción).
- Definidos en el **Paso 1**: `domain/entities.py` (`Appointment`),
  `domain/ports.py` (`AppointmentRepositoryPort`) e
  `infrastructure/in_memory.py` (`InMemoryAppointmentRepository`, el doble con el que
  corren los tests hasta que exista el adapter real en el Paso 6). `LegacyOpsPort`
  y los contratos expuestos llegan con los Pasos 5 y 11.
- Definidos en el **Paso 3**: `domain/rules.py` (datos mínimos), `domain/errors.py`
  (`IncompleteAppointmentData`, `TenantMismatch`) y `application/`
  (`state.py`, `schemas.py`, `prompts.py`, `tools.py`, `deps.py`, `nodes/`, `graph.py`).

## Grafo (Paso 3)
- `application/graph.py` → `build_appointment_graph(llm, repo, clock, opening_hours)`.
  Nodos en `application/nodes/`: `understand` (LLM → JSON validado en
  `AppointmentProposal`, con reintento único y degradación a aclaración), `validate` +
  `need_more?` (regla 4), `select_action` (allowlist `ALLOWED_TOOLS`; sin `tool_name` si
  no aplica), `call_tool` (despacho; un `AppError` de la tool se traduce en `tool_error`),
  `validate_result` + `needs_confirmation?` (coherencia del resultado y confirmación) y
  `respond` (redacción con los datos ya decididos).
- `AgentState` (`application/state.py`): el llamador pone `tenant_id`, `correlation_id`,
  `user_message` y `history`; el resto lo escriben los nodos (`NotRequired`).
- Dos llamadas al LLM por turno (interpretar y redactar). **Sin checkpointer**: la
  ventana de historial y el comercio los aporta el llamador, nunca el modelo
  (`TODO(decision)`: multi-turno con checkpointer en el Paso 8; confirmación previa
  real con HITL en los Pasos 5/8 — hoy `create_appointment` guarda `pending` y la
  respuesta solo pide confirmación).
- `application/tools.py`: las 4 tools sobre `AppointmentRepositoryPort` en memoria,
  `ClockPort` y el horario inyectado; la disponibilidad es horario − citas ocupadas −
  huecos pasados. `TODO(decision)`: zona horaria compartida al conectar Aurora (Paso 6).

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| Aurora PostgreSQL (tabla `appointments`) | Historial y estado de las citas creadas | 6 |
| APIs legacy `ops_service` vía AgentCore Gateway + Policy | Disponibilidad y creación reales del comercio | 11 |
| DynamoDB `appointment_locks` (TTL corto) | Idempotencia de `create_appointment` por `correlation_id` | 6 |
| CloudWatch Logs | Auditoría de cada invocación de tool | 5 |

## Reglas de negocio clave
1. Todo dato se filtra por el `tenant_id` resuelto en el gateway: jamás se consulta o
   crea una cita de otro comercio aunque el LLM lo pida.
2. No solapes: dos citas del mismo comercio no ocupan el mismo turno.
3. Toda cita cae dentro del horario de atención del comercio (festivos:
   TODO(decision)).
4. Confirmación humana obligatoria: si faltan fecha, hora o datos del cliente, el bot
   pide la información y NO crea la cita.
5. Datos mínimos para crear: fecha, hora, nombre y medio de contacto del cliente.
6. `cancel_appointment` solo sobre citas existentes, del mismo tenant y en estado
   cancelable.
7. La disponibilidad y los horarios nunca los inventa el LLM: salen de la tool o del
   backend.

## Tools expuestas al LLM
| Tool | Esquema resumido | Notas de seguridad |
|---|---|---|
| `get_availability` | `{date, party_size?}` → `[slot]` | Solo lectura; filtra por el tenant del contexto |
| `create_appointment` | `{date, time, customer, contact}` → cita | Idempotente por `correlation_id`; en el Paso 3 guarda `pending` y la respuesta pide confirmación (HITL real: Pasos 5/8); timeout al legacy (Paso 5) |
| `cancel_appointment` | `{appointment_id}` → estado | Autoriza por tenant y estado; log de auditoría |
| `get_opening_hours` | `{}` → horarios | Si procede del conocimiento, delega en RAG con `tenant_id` |

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `SlotUnavailable` | El turno ya está ocupado en el legacy | "Ese horario ya no está disponible" + log warn |
| `OutsideOpeningHours` | Fecha/hora fuera del horario | Sugerir un turno válido + log warn |
| `IncompleteAppointmentData` | Faltan datos mínimos | El bot pide los datos; no se crea nada + log info |
| `LegacyTimeout` | `ops_service` no responde en el timeout | Disculpa al usuario + log error con `correlation_id` |
| `TenantMismatch` | La cita pertenece a otro tenant | Rechazo genérico sin detalles + log error |

`IncompleteAppointmentData` y `TenantMismatch` existen desde el **Paso 3**
(`domain/errors.py`); el resto de errores de la tabla llegan con el **Paso 5**.

## Cómo probarlo
- `tests/unit/` (Paso 1, hecho): `test_appointments_repository.py` — el doble cumple el
  port, aislamiento por tenant, idempotencia por `correlation_id`, periodo de consulta
  y entidad inmutable.
- `tests/unit/` (Paso 3, hecho): `test_appointments_rules.py` (datos mínimos),
  `test_appointments_tools.py` (disponibilidad pasada/ocupada, idempotencia,
  cancelación y aislamiento por tenant) y `test_appointments_graph.py` (nodos sueltos,
  allowlist sincronizada con `ToolName`, cuatro end-to-end y el negativo: un JSON con
  `tenant_id` ajeno degrada a aclaración y no ejecuta nada).
- Pendiente (Paso 5): `tests/contract/` — esquemas de `AppointmentCreate` y
  `AvailabilitySlot`, y que la tool no acepta `tenant_id` en el payload.
- Pendiente (Paso 14): `tests/agent_evals/datasets/` — "quiero una cita el viernes" sin
  hora → pide confirmación en vez de crear; "cita para otro comercio" → rechazo por tenant.
