# Slice: supervisor

> Paso de implementación: **Paso 4**. Estado: **implementado** — clasificación de
> intención, ruta propia de saludo, `allowed_bots`, contexto obligatorio por turno y
> nodo anidado que invoca el grafo de citas. **Fase 3 del Paso 5**: el nodo anidado
> `route_orders` invoca el grafo de pedidos cuando la composición lo inyecta
> (`orders_graph=None` → `route_pending`). **Fase 4 del Paso 5**: nodo `resolve_pending`
> (router determinista de drafts, ADR 0011 §5) con `ConfirmerPort` y `DraftStorePort`
> opcionales (`None` → router desactivado). **Fase 5 del Paso 5**: confirmer real
> cableado en la composición del REPL (`scripts/chat_citas.py`) y evals e2e de
> citas/pedidos que pasan por este supervisor. **Paso 7**: el nodo `route_faq`
> invoca el grafo `faq` de `knowledge_rag` cuando la composición lo inyecta
> (`faq_graph=None` → `route_pending`, retrocompatible). **Paso 8 (Fase 2)**: nodo
> `window_history` entre `load_context` y `resolve_pending` que recorta la ventana a
> `history_window_size` (10 por defecto, `CHATBOT_HISTORY_WINDOW_SIZE`) y reduce lo
> desbordado a resumen rodante en `SupervisorState.summary`. Handoff y abuso
> (`sentiment_handoff`, `abuse_protection`) siguen fuera de la ruta (ROADMAP §4).

## Responsabilidad

Recibe el mensaje normalizado del gateway, decide la intención (`greeting`/`smalltalk`,
`sales`, `appointments`, `orders`, `faq`) y enruta al agente/especialista adecuado — o
responde él mismo en el caso del saludo. Aplica también la salida temprana de handoff
(`sentiment_handoff`) y la de abuso (`abuse_protection`), cuando existan. NO ejecuta
tools de negocio.

## Entradas y salidas

- Entradas: contrato `InboundMessage` (con `tenant_id` y `correlation_id` ya
  resueltos) + la ventana `history` (obligatoria: el turno sin historial falla en el
  primer nodo).
- Salidas: `reply` directo (saludo, degradaciones) o contrato `RoutedTurn` (mensaje +
  intención + agente destino); `route_error` para logs/métricas cuando el enrutado se
  rechazó.

## Grafo (Paso 4)

- `application/graph.py` → `build_supervisor_graph(llm, context_reader, allowed_bots,
  appointments_graph, orders_graph=None, faq_graph=None, draft_store=None,
  confirmer=None, history_window_size=10)`. Nodos en
  `application/nodes/`:
  `load_context` (exige `history`; lee el contexto con los ids del mensaje y falla si
  no lo hay), `window_history` (Paso 8: recorta `history` a la ventana; si hay
  desbordado pide el resumen con `TAREA_RESUMEN` y lo guarda en `summary`, como
  primer mensaje sintético de la ventana; fallo del proveedor → conserva el resumen
  previo y sigue con log `supervisor.summary_failed`, sin desbordado no llama al
  LLM), `resolve_pending` (Fase 4 del Paso 5: si hay draft `AWAITING_CONFIRMATION`
  en la ranura única de la conversación, decide «sí/no» con match exacto normalizado —
  `domain/pending.py` — o con el LLM de respaldo `TAREA_PENDIENTE` que debe eco el
  `payload_hash`; si solo hay un draft `COMMITTED` con ventana abierta, «cancelar»
  exacto hace `undo`; resuelto → `reply` plantilla + `pending_outcome` y el turno
  termina; sin match, hash desfasado, JSON ilegible, proveedor caído o `AppError` del
  confirmer → degrada con log y el turno sigue normal), `classify` (LLM → JSON
  `SupervisorDecision` con reintento; proveedor caído
  → palabras clave con log; salida ilegible → `confidence=0.0`), `decide`
  (`resolve_route` del dominio; sus errores se traducen a `reply` + `route_error`),
  `greet` (saludo neutral propio), `route_appointments`, `route_orders` y `route_faq`
  (Paso 7: espejo de `route_orders` sin `conversation_id`; si `faq_graph` es `None` o
  no devuelve `reply`, degrada con `_MSG_SIN_RESPUESTA` + log
  `supervisor.empty_specialist_reply`) y `route_pending` (deja el `RoutedTurn`
  para ventas/faq y para pedidos cuando su grafo no está inyectado).
  Aristas: `START → load_context → window_history → resolve_pending →
  {classify | END}` (la ruta la fija
  `ruta_tras_pendiente`: `END` solo cuando el router escribió `reply`).
  La ruta condicional `ruta_tras_decidir` solo manda a `route_orders`/`route_faq` si
  el grafo correspondiente existe; en caso contrario va a `route_pending`
  (retrocompatible).
- `SupervisorState` (`application/state.py`): el llamador pone `message` e `history`;
  `summary` lo escribe `window_history` (resumen rodante, Paso 8); el resto lo
  escriben los nodos (`NotRequired`).
- El prompt del clasificador siempre incluye el bloque de contexto y la ventana de
  historial (requisito 7.2; hay tests que fallan si faltan).

## Ports

- Expone: contrato `RoutedTurn` (mensaje + intención + agente destino).
- Consume: `LLMPort` (`shared/ports/`, implementado en `adapters/bedrock`), el lector
  de contexto de `customer_context` y el grafo de citas de `appointments` — **sin
  importarlos**: llegan como puertos del propio dominio (`ContextReaderPort`,
  `SpecialistGraphPort`) y la composición ocurre fuera (handler, REPL o tests).
  Desde la **Fase 4 del Paso 5** también `DraftStorePort` (`shared/ports/`) y el
  `ConfirmerPort` del propio dominio (`domain/ports.py`: `affirm`/`deny`/`undo` con
  `tenant_id`, `draft_id` y `payload_hash`); ambos se inyectan opcionales en `Deps`
  y su implementación real (el confirmer del especialista) se cablea en Fase 5.
- Definidos en el **Paso 4**: `domain/errors.py` (`AmbiguousIntentError`,
  `IntentNotAllowedByTenant`, `MissingTurnInputsError`), `domain/ports.py`
  (`ContextReaderPort`, `SpecialistGraphPort`), `domain/routing.py` (`resolve_route`,
  `intent_from_keywords`, `saludo`), `application/` (`state.py`, `schemas.py`,
  `prompts.py`, `deps.py`, `nodes/`, `graph.py`) y `prompts/base/supervisor.md`.
  Desde la **Fase 4 del Paso 5**: `domain/pending.py` (conjuntos exactos de
  respuesta + plantillas `affirmed`/`denied`/`undoed`), `ConfirmerPort`,
  `application/schemas.py::PendingAnswer`, `nodes/resolve_pending.py` y
  `prompts.py::TAREA_PENDIENTE`. Desde el **Paso 8**: `domain/history.py`
  (`split_window`, `summary_message`, `is_summary`, `without_summary`),
  `nodes/window_history.py` y `prompts.py::TAREA_RESUMEN`.

## Tablas y recursos AWS

| Recurso | Por qué | Paso |
|---|---|---|
| Bedrock (modelo clasificador) | Decisión de intención barata y configurable | 4 |
| Prompt `supervisor` (archivos locales; Prompt Management fuera de la ruta) | Clasificación versionada por tenant | 4 |
| DynamoDB (métrica de intenciones, opcional) | Dashboards de uso por tenant | 4/13 |

## Reglas de negocio clave

1. **El saludo tiene ruta propia**: intención `greeting`/`smalltalk` → respuesta neutral
   propia del supervisor ("Buenas, bienvenido a {comercio}, ¿en qué te ayudo?") usando
   solo el nombre/branding del contexto del tenant (`TODO(decision)`: branding real,
   hoy el `tenant_id`); **jamás** se enruta a ventas (regresión obligatoria: test unit +
   dataset `greeting_01`).
2. La clasificación es una **decisión de orquestación**, no una regla de negocio: el
   prompt solo clasifica; el enrutado vive en código (`domain/routing.py`).
3. Todo turno pasa primero por `abuse_protection` y `sentiment_handoff`: si alguno marca
   salida (`blocked` o `human_takeover`), el supervisor no invoca agentes (cuando
   existan; fuera de la ruta).
4. Intención desconocida o baja confianza (umbral `0.5`, `TODO(verify)`) → respuesta
   honesta del supervisor con `route_error=ambiguous_intent`; nunca inventar. La
   intención `faq` sí tiene ruta propia desde el **Paso 7**: `route_faq` invoca el
   grafo de `knowledge_rag` cuando está inyectado (ADR 0010); la ambigüedad no se
   delega al RAG, sigue con respuesta honesta.
5. `allowed_bots` del tenant restringe las rutas disponibles (p. ej. comercio sin citas
   → nunca enruta a `appointments`, responde «servicio no disponible»). `supervisor`
   (saludo) y `faq` no dependen de entitlements.
6. Contexto obligatorio por turno (requisito 7.2): sin `history` o sin contexto, el
   turno **falla** en `load_context` — el prompt jamás se construye incompleto.
7. **Router determinista de drafts (ADR 0011 §5, Fase 4 del Paso 5)**: mientras haya un
   draft `AWAITING_CONFIRMATION` en la conversación, «sí»/«no» exactos (normalizados)
   cierran el draft **sin clasificar ni invocar especialista**, con plantilla genérica;
   el LLM de respaldo (`TAREA_PENDIENTE`) solo clasifica respuestas libres y debe eco
   el `payload_hash` exacto. Sobre un draft `COMMITTED` dentro de su ventana,
   «cancelar» exacto hace `undo`. Cualquier fallo (hash desfasado, JSON ilegible,
    proveedor caído, `AppError` del confirmer, draft expirado) degrada con log
    `supervisor.pending_resolution_failed` al agente normal: nunca se confirma a medias
    y el saludo sigue teniendo su ruta propia (hay test de regresión con draft esperando).
8. **Ventana acotada con resumen (Paso 8)**: el clasificador nunca ve más de
   `history_window_size` mensajes (10 por defecto); lo que desborda se reduce a un
   resumen que solo resume — no decide ni aplica reglas — y viaja como primer mensaje
   de la ventana. El resumen es rodante (el previo se pasa al modelo) y nunca se
   re-resume a sí mismo; si el proveedor falla, se conserva el resumen previo y el
   turno sigue (log warn `supervisor.summary_failed`).

## Tools expuestas al LLM

Ninguna de negocio. El supervisor solo usa el prompt de clasificación (sin tools) o
responde con el saludo plantilla del tenant.

## Errores esperados

| Error | Cuándo | Traducción |
|---|---|---|
| `AmbiguousIntentError` | Confianza por debajo del umbral `0.5` (`TODO(verify)`) | `reply` honesto («No estoy seguro de entender...») + `route_error=ambiguous_intent` + log info |
| `IntentNotAllowedByTenant` | Intención válida pero no en `allowed_bots` | `reply` «Ese servicio aún no está disponible...» + `route_error=intent_not_allowed` + log info |
| `MissingTurnInputsError` | Turno sin historial, sin texto o sin contexto | El turno **falla** en el primer nodo (regresión 7.2) |
| Fallo de `LLMPort` | Bedrock caído | Clasificación por palabras clave + log warn `supervisor.keyword_fallback` |
| Fallo de `LLMPort` al resumir | Bedrock caído en `window_history` | Se conserva el resumen previo (o ninguno) y el turno sigue + log warn `supervisor.summary_failed` |
| Especialista sin `reply` | El grafo de citas/pedidos/faqs no redactó (no debería) | Mensaje honesto de reintento + log warn `supervisor.empty_specialist_reply` |

## Cómo probarlo

- Unit (hecho): `tests/unit/test_supervisor_routing.py` (tabla intención→destino,
  saludo nunca a ventas, `allowed_bots`, umbral, palabras clave, saludo) y
  `tests/unit/test_supervisor_graph.py` (nodos sueltos, prompt con contexto+historial,
  turnos sin contexto/historial fallan, saludo sin invocar a nadie, citas invocan al
  especialista conservando ids, fallo de Bedrock → palabras clave; Fase 3 del Paso 5:
  pedidos invocan `route_orders` con `conversation_id` compuesto, sin `orders_graph`
  caen en `route_pending` y `ruta_tras_decidir` distingue ambas rutas; Paso 7:
  `route_faq` comparte `tenant_id`/`correlation_id`/`history` **sin**
  `conversation_id`, `faq_graph=None` o sin `reply` degrada a mensaje honesto y
  `ruta_tras_decidir` solo manda a `route_faq` si el grafo está inyectado).
- Unit router (Fase 4 del Paso 5, hecho): `tests/unit/test_supervisor_resolve_pending.py`
  — match exacto sí/no sin LLM, respaldo con eco de `payload_hash`, hash desfasado y
  JSON ilegible pasan al agente, draft expirado, undo dentro/fuera de ventana,
  confirmer caído degrada con log, router no inyectado retrocompatible, e2e «sí» sin
  clasificador y **saludo intacto con draft esperando**.
- Unit ventana/resumen (Paso 8, hecho): `tests/unit/test_supervisor_history.py`
  (`split_window` y mensajes sintéticos del dominio; nodo sin desbordado no llama al
  LLM, desbordado recorta y resume, resumen previo viaja/actualiza, fallo o salida
  vacía del LLM conserva el resumen previo, el sintético no se re-resume, ventana
  personalizada y turno sin historial) + e2e en `test_supervisor_graph.py`
  (12 mensajes → resumen primero y clasificación con la ventana de 10).
- Eval (hecho): `tests/agent_evals/datasets/supervisor_routing.json` con su ejecutor
  `tests/agent_evals/test_supervisor_dataset.py` (`greeting_01/02`, `appointments_01`,
  `orders_01`, `allowed_bots_01`, `ambiguous_01`); el build falla si el saludo enruta
  a ventas o invoca un especialista.
- Contract: el `RoutedTurn` siempre lleva `tenant_id`/`correlation_id` (asertado en el
  grafo y en el dataset).
- Manual contra Bedrock (hecho el 2026-10-08 y extendido el 2026-10-09 en la Fase 5,
  cuenta `iastock-old`): REPL `python scripts\chat_citas.py` pasando por el supervisor
  (`hola` → saludo propio; cita → `intencion=appointments`; pedido → `intencion=orders`;
  alto monto → draft a la espera y «sí» → `pending_outcome=affirmed` con pedido creado)
  y smoke `tests/integration/test_supervisor_smoke.py` (`3 passed` con perfil
  `iastock-old`, incluida la ruta `route_orders`; en CI se omite sin credenciales).
