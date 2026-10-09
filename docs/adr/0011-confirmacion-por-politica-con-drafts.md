# 0011. Confirmación por política de riesgo con drafts propose/commit

- **Estado:** Aceptado
- **Fecha:** 2026-10-09
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

Las reglas 3 de `orders` y 4 de `appointments` exigen confirmación antes de crear un
pedido o una cita. Dos problemas con la obvia:

1. **Un ritual fijo** («escribe sí/confirmo» en todos los casos) da indicio de chatbot,
   cansa al usuario y encarece cada conversación: el cliente recurrente que pide «lo de
   siempre» no debería pagar el mismo peaje que una acción riesgosa.
2. **Recordar la propuesta entre turnos** exige memoria conversacional, que hoy no
   existe (checkpointer: Paso 8) y que con `interrupt()` de LangGraph ataría un flujo
   de negocio a un hilo suspendido del grafo, complicando el escalado futuro (SQS,
   ADR 0006, entrega al menos una vez).

Además, la creación de un pedido o una cita debe ser **idempotente y atómica** cuando
llegue la infraestructura: nada de duplicados por doble entrega ni escrituras a medias.

## Decisión

**El LLM propone, la plataforma confirma y ejecuta.** La confirmación es una
**política por riesgo**, no una regla fija. Implica:

1. **Tools de escritura solo `propose_*`**: `propose_appointment` y `propose_order`.
   El agente no tiene ninguna tool que cree ni modifique datos reales; una alucinación
   o un prompt injection no pueden ejecutar nada.
2. **Draft persistido fuera del agente**: `PendingDraft` (`shared/contracts/`) +
   `DraftStorePort` (`shared/ports/`); doble en memoria desde el Paso 5
   (`adapters/in_memory/`), tabla DynamoDB `pending_actions` con TTL en el Paso 6.
   Un solo draft activo por conversación; cualquier confirmación posterior va ligada al
   `payload_hash` del contenido exacto propuesto.
3. **Política determinista en `domain/`** (un `decide(draft, customer, cfg)` por slice):
   devuelve `AUTO` o `CONFIRM` con sus `reasons` (slots inferidos, monto sobre umbral,
   cliente nuevo, acción con penalidad...). Código testeable sin LLM; umbrales
   iniciales con `TODO(decision)`.
4. **Máquina de estados del draft**:
   `DRAFTED → AUTO_APPROVED → COMMITTED`;
   `DRAFTED → AWAITING_CONFIRMATION → CONFIRMED → COMMITTED`;
   modificación → `SUPERSEDED` (draft nuevo); TTL → `EXPIRED`; cancelación o deshacer
   → `CANCELLED`.
5. **Router determinista antes del agente**: nodo `resolve_pending` del `supervisor`.
   Si hay draft `AWAITING_CONFIRMATION`, clasifica la respuesta (match exacto de
   «sí/no» + LLM estructurado de respaldo que verifica el `payload_hash`) y confirma o
   cancela con **respuesta plantilla, sin invocar al especialista**; cualquier otra
   cosa pasa al agente con el draft en contexto. Auto-commit lleva ventana de
   deshacer (`undo_until`); «CANCELAR» dentro de la ventana cancela.
6. **Defensa en profundidad del commit**: la transición a `COMMITTED` solo se acepta
   desde `AUTO_APPROVED` o `CONFIRMED` — validada en el dominio y **exigida por el
   store** (hoy el doble en memoria; en el Paso 6, la `ConditionExpression`
   transaccional de DynamoDB). Idempotencia por `draft_id`/`correlation_id`.
7. **Checkpointer (Paso 8) ≠ `pending_actions`**: el checkpointer es memoria
   conversacional del grafo; el draft es estado de negocio con garantías. La
   confirmación no depende del primero ni usa `interrupt()`; ese patrón queda
   reservado para aprobación de operador futuro.
8. **Botones nativos**: el router acepta ya un `button_payload` (draft_id + hash);
   su emisión real llega con el canal (Paso 9) `TODO(verify)`.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Confirmación fija siempre («escribe sí») | Regla única y fácil de explicar. | Dos turnos extra en todos los casos; da indicio de chatbot; los clientes recurrentes se cansan. | Se descarta: la confirmación es una política de riesgo, no un ritual. |
| Confirmación recordada por el LLM (slots en el state/checkpointer) | Sin tabla nueva ni router. | Depende del Paso 8; sin garantías transaccionales ni idempotencia; el modelo puede «recordar» mal el contenido a confirmar. | Se descarta: la verdad del draft no puede vivir en la memoria del grafo. |
| LangGraph `interrupt()` / HITL suspendido | Soporte «de fábrica» para esperar al usuario. | Ata el negocio a un hilo suspendido del grafo; complica el escalado con colas (SQS) y la recuperación de fallos. | Se descarta para confirmación de cliente; reservado para aprobación de operador. |
| Sin drafts: tool `create_*` directa con la política en el prompt | Menos piezas. | El LLM decidiría cuándo confirmar (reglas de negocio en prompts, prohibido); sin commit atómico ni idempotencia verificable. | Se descarta por las reglas 1 y 3 de `AGENTS.md` §5. |

## Consecuencias

### Positivas

- Los casos de bajo riesgo no pagan peaje de confirmación; el riesgoso sigue protegido.
- La política es código determinista: tests unit por regla, sin LLM de por medio.
- El «sí» no depende del checkpointer ni de `interrupt()`: funciona igual en el Paso 5
  y después del Paso 8.
- Defensa en profundidad real: aunque el agente proponga de más, el commit solo sale
  desde `AUTO_APPROVED`/`CONFIRMED` (store/ConditionExpression como última capa).
- Métricas accionables (tasa de auto-commit, de deshacer y de expirados) para ajustar
  umbrales con tráfico real (Paso 13).

### Negativas / riesgos

- Pieza de estado nueva (`pending_actions`) que hay que persistir con TTL (Paso 6) y
  limpiar: un commit interrumpido a mitad deja un draft huérfano que expira solo.
- Umbrales de política `TODO(decision)` al inicio: un umbral mal puesto auto-aprueba de
  más o molesta de más; se corrige con las métricas.
- El router añade un nodo antes de clasificar en el supervisor: si falla, se degrada a
  «agente normal» con log, nunca silenciosamente.
- Doble superficie (draft + entidad final): hay que mantener sincronizados hash,
  estados y deshacer.

## Relacionados

- [0005. Comunicación entre slices vía contracts](0005-comunicacion-entre-slices-via-contracts.md)
- [0006. Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md)
- [0010. Composición de grafos por invocación](0010-composicion-de-grafos-por-invocacion.md)
- [Slice orders](../../src/slices/orders/AGENTS.md) (defensa en profundidad de la hora)
- [Guía de memoria y contexto](../ai/MEMORY_AND_CONTEXT.md)
