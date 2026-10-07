# Slice: appointments

> Fase de implementación: **Fase 6**. Estado: **definido, sin implementar** (el detalle
> funcional se completa en su fase; este documento es el contrato previo).

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

## Tablas y recursos AWS
| Recurso | Por qué | Fase |
|---|---|---|
| Aurora PostgreSQL (tabla `appointments`) | Historial y estado de las citas creadas | 6 |
| APIs legacy `ops_service` vía AgentCore Gateway + Policy | Disponibilidad y creación reales del comercio | 6 |
| DynamoDB `appointment_locks` (TTL corto) | Idempotencia de `create_appointment` por `correlation_id` | 6 |
| CloudWatch Logs | Auditoría de cada invocación de tool | 6 |

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
| `create_appointment` | `{date, time, customer, contact}` → cita | Idempotente por `correlation_id`; exige confirmación previa; timeout al legacy |
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

## Cómo probarlo
- `tests/unit/`: domain de `appointments` — solape rechazado, fecha fuera de horario
  rechazada y datos incompletos que no llegan a crear la entidad.
- `tests/contract/`: esquemas de `AppointmentCreate` y `AvailabilitySlot`, y que la
  tool no acepta `tenant_id` en el payload.
- `tests/agent_evals/datasets/`: "quiero una cita el viernes" sin hora → pide
  confirmación en vez de crear; "cita para otro comercio" → rechazo por tenant.
