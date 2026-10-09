# Slice: supervisor

> Paso de implementación: **Paso 4**. Estado: **implementado** — clasificación de
> intención, ruta propia de saludo, `allowed_bots`, contexto obligatorio por turno y
> nodo anidado que invoca el grafo de citas. Handoff y abuso (`sentiment_handoff`,
> `abuse_protection`) siguen fuera de la ruta (ROADMAP §4).

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
  appointments_graph)`. Nodos en `application/nodes/`:
  `load_context` (exige `history`; lee el contexto con los ids del mensaje y falla si
  no lo hay), `classify` (LLM → JSON `SupervisorDecision` con reintento; proveedor caído
  → palabras clave con log; salida ilegible → `confidence=0.0`), `decide`
  (`resolve_route` del dominio; sus errores se traducen a `reply` + `route_error`),
  `greet` (saludo neutral propio), `route_appointments` (invoca el grafo de citas ya
  compilado, ADR 0010) y `route_pending` (deja el `RoutedTurn` para ventas/pedidos/faq,
  grafos aún no construidos).
- `SupervisorState` (`application/state.py`): el llamador pone `message` e `history`;
  el resto lo escriben los nodos (`NotRequired`).
- El prompt del clasificador siempre incluye el bloque de contexto y la ventana de
  historial (requisito 7.2; hay tests que fallan si faltan).

## Ports

- Expone: contrato `RoutedTurn` (mensaje + intención + agente destino).
- Consume: `LLMPort` (`shared/ports/`, implementado en `adapters/bedrock`), el lector
  de contexto de `customer_context` y el grafo de citas de `appointments` — **sin
  importarlos**: llegan como puertos del propio dominio (`ContextReaderPort`,
  `SpecialistGraphPort`) y la composición ocurre fuera (handler, REPL o tests).
- Definidos en el **Paso 4**: `domain/errors.py` (`AmbiguousIntentError`,
  `IntentNotAllowedByTenant`, `MissingTurnInputsError`), `domain/ports.py`
  (`ContextReaderPort`, `SpecialistGraphPort`), `domain/routing.py` (`resolve_route`,
  `intent_from_keywords`, `saludo`), `application/` (`state.py`, `schemas.py`,
  `prompts.py`, `deps.py`, `nodes/`, `graph.py`) y `prompts/base/supervisor.md`.

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
   honesta del supervisor con `route_error=ambiguous_intent`; nunca inventar. Cuando
   exista `knowledge_rag` (Paso 7) esta ruta pasará al agente `faq` (ADR 0010).
5. `allowed_bots` del tenant restringe las rutas disponibles (p. ej. comercio sin citas
   → nunca enruta a `appointments`, responde «servicio no disponible»). `supervisor`
   (saludo) y `faq` no dependen de entitlements.
6. Contexto obligatorio por turno (requisito 7.2): sin `history` o sin contexto, el
   turno **falla** en `load_context` — el prompt jamás se construye incompleto.

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
| Especialista sin `reply` | El grafo de citas no redactó (no debería) | Mensaje honesto de reintento + log warn `supervisor.empty_specialist_reply` |

## Cómo probarlo

- Unit (hecho): `tests/unit/test_supervisor_routing.py` (tabla intención→destino,
  saludo nunca a ventas, `allowed_bots`, umbral, palabras clave, saludo) y
  `tests/unit/test_supervisor_graph.py` (nodos sueltos, prompt con contexto+historial,
  turnos sin contexto/historial fallan, saludo sin invocar a nadie, citas invocan al
  especialista conservando ids, fallo de Bedrock → palabras clave).
- Eval (hecho): `tests/agent_evals/datasets/supervisor_routing.json` con su ejecutor
  `tests/agent_evals/test_supervisor_dataset.py` (`greeting_01/02`, `appointments_01`,
  `orders_01`, `allowed_bots_01`, `ambiguous_01`); el build falla si el saludo enruta
  a ventas o invoca un especialista.
- Contract: el `RoutedTurn` siempre lleva `tenant_id`/`correlation_id` (asertado en el
  grafo y en el dataset).
- Manual contra Bedrock (hecho, 2026-10-08): REPL `python scripts\chat_citas.py` pasando
  por el supervisor (`hola` → saludo propio; cita → `intencion=appointments` con
  enrutado al especialista) y smoke `tests/integration/test_supervisor_smoke.py`
  (`2 passed` con perfil `iastock-old`; en CI se omite sin credenciales).
