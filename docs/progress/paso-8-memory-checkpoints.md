# Progreso — Paso 8: Memory / checkpoints

> **Checklist vivo del Paso 8.** Se actualiza tras cada commit de la fase: `[x]` hecho,
> `[~]` en curso, `[ ]` pendiente. Es la respuesta rápida a «¿qué se hizo y qué falta?»
> sin releer el código. Criterio de cierre del paso:
> [ROADMAP §1 fila 8](../ROADMAP.md). Decisiones de alcance: ADR 0013 (Fase 5).
>
> **Estado global: PASO 8 EN CURSO (Fase 1 de 5); siguiente tras el cierre: Paso 9
> (Conversation gateway).**

## Decisiones cerradas con el usuario (2026-10-10)

- [x] Checkpointer **custom** (`BaseCheckpointSaver` sobre `MemoryStorePort`) en vez
      de un paquete oficial: cumple «tras port» del ROADMAP y evita dependencia de un
      paquete DynamoDB que habría que verificar (`TODO(verify)` ya no aplica a la API:
      verificada contra langgraph 1.2.14 + langgraph-checkpoint 4.2.0).
- [x] Alcance: **solo el grafo del supervisor** (los especialistas se invocan dentro
      del turno, ADR 0010, y no necesitan persistencia propia).
- [x] Tabla dedicada **`chatbot_checkpoints`** en Terraform (Fase 4) en vez de
      reusar `chatbot_conversations`.
- [x] **ADR 0013** nuevo (checkpointer y ventana) en la Fase 5.

## Decisiones técnicas de la Fase 1

- [x] **`thread_id` con tenant embebido**: formato `<tenant_id>#<conversation_id>`
      (`thread_id_de`); el tenant lo pone el llamador que resolvió el contexto, nunca
      el payload del LLM, y permite `delete_thread` sin estado auxiliar.
- [x] **Solo el checkpoint más reciente** por conversación (envelope JSON con sus
      writes pendientes): los grafos no usan `interrupt()` ni time-travel;
      `TODO(verify)` si algún flujo futuro necesita ramificación.
- [x] **Envelope JSON puro** con el serde de LangGraph (msgpack en base64) para los
      tipos no JSON (datetime, bytes): es lo que exige `MemoryStorePort.payload: str`.

## Fase 1 — checkpointer tras el port  (en curso)

- [x] `adapters/checkpointer/`: `PortCheckpointSaver(BaseCheckpointSaver)` con
      `get_tuple`/`put`/`put_writes`/`list`/`delete_thread` + versiones `a*` que
      delegan; errores tipados (`ValidationError` de `shared`), logs `checkpointer.*`
      con `tenant_id`/`conversation_id` y TTL pasado al port.
- [x] `adapters/in_memory/memory.py`: `InMemoryMemoryStore` (doble del port; ignora
      TTL por no llevar reloj).
- [x] `shared/ports/memory.py`: docstring actualizado (el `TODO(verify)` de la API del
      checkpointer queda cerrado); contrato del port **sin cambios**.
- [x] Tests: `test_adapters_port_checkpoint_saver.py` (round-trip, padres, writes,
      aislamiento por hilo/tenant, envelope JSON, formatos inválidos, async) +
      `test_adapters_in_memory_memory.py`.

## Fase 2 — política de ventana + resumen  (pendiente)

- [ ] Ventana de historial `N=10` (`HISTORY_WINDOW_SIZE`, `TODO(verify)`) como regla
      de negocio en domain del supervisor.
- [ ] Paso de resumen con LLM barato cuando se desborda la ventana; el resumen solo
      resume (no decide ni aplica reglas).
- [ ] Tests de la política (recorte, resumen, degradación si el LLM falla).

## Fase 3 — cableado del checkpointer en el supervisor + evals  (pendiente)

- [ ] `build_supervisor_graph(..., checkpointer=None)` (opcional y retrocompatible).
- [ ] El grafo recuerda el turno (historial con ventana + resumen) y la conversación
      sobrevive invocaciones distintas con `thread_id`.
- [ ] Evals: dos invocaciones encadenadas conservan el hilo; **cero fuga** de estado
      entre conversaciones y entre tenants.

## Fase 4 — DynamoDB + Terraform  (pendiente)

- [ ] `adapters/dynamodb/`: `DynamoDBMemoryStore(MemoryStorePort)` (put/get/delete,
      TTL, errores traducidos a `ToolError`, timeout) + settings de la tabla.
- [ ] Tabla `chatbot_checkpoints` (PK/SK, TTL) en `infra/modules/dynamodb` + cableado
      en los 3 envs + IAM de la Lambda supervisor (`TODO(verify)` de acciones mínimas).
- [ ] Tests con el cliente mockeado (sin AWS real).

## Fase 5 — ADR 0013 + docs + cierre  (pendiente)

- [ ] ADR 0013 (checkpointer custom tras port, `thread_id` con tenant, ventana y
      resumen, tabla dedicada) + índice ADR.
- [ ] AGENTS (raíz §10 fila 8 → hecho, `shared`, `supervisor`, `adapters`, índice de
      slices si procede), `MEMORY_AND_CONTEXT.md`, `CLAUDE.md` → paso 9, REPL con
      checkpointer y este checklist.
- [ ] Batería completa en verde (ruff, format, mypy, pytest, lint-imports,
      terraform fmt, final_review, pyrefly).

## Criterios de hecho del ROADMAP (§1 fila 8)

- [ ] **La conversación sobrevive a invocaciones distintas**: mismo `thread_id` en
      turnos separados recupera el estado (eval Fase 3).
- [ ] **Sin fuga de estado entre invocaciones**: conversaciones/tenants distintos no
      comparten nada (eval Fase 3).
- [ ] Batería completa en verde al cierre de la Fase 5.

## Pendientes explícitos (no bloquean el cierre)

- `TODO(verify)`: tamaño de ventana N=10 y cadencia de resumen con evals; si algún
  flujo futuro necesita time-travel o ramificación de checkpoints; acciones IAM
  mínimas de la Lambda; límite real de tamaño del payload por conversación.
- `TODO(decision)`: plazo de retención del estado de conversación (vinculado al
  ADR 0007, todavía pendiente).
