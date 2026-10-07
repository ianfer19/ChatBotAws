# Memoria y contexto

Los tres niveles de memoria de ChatBotAws y el contexto obligatorio de cada turno.

## Los tres niveles

| Nivel | Almacenamiento | Vida | Quién escribe | Quién lee | ¿Fuente de verdad? |
|---|---|---|---|---|---|
| Conversation state | DynamoDB + checkpointer de LangGraph | Sesión (ventana + resumen); retención sujeta a política | Orquestador (turno a turno) | Supervisor y especialistas | No |
| Memoria a largo plazo | AgentCore Memory | Permanente con retención configurable | Eventos relevantes del orquestador | Prompts/respuestas vía tools | No |
| Datos de negocio | Backend legacy (vía tools) | Según el sistema legacy | El negocio (pedidos, citas) | Tools con schema y autorización | **Sí** |

Regla transversal: **la memoria nunca es fuente de verdad operacional**. Precios,
stock, disponibilidad, estados de pedido y horas siempre salen del legacy.

## Conversation state (nivel 1)

- **Almacenamiento**: DynamoDB como respaldo del estado de conversación; el
  orquestador LangGraph persiste su estado con un checkpointer.
- **Checkpointer**: adaptador sobre DynamoDB. `TODO(verify)` del adaptador
  concreto y de su API (checkpoint, thread id, resumenes) según la versión de
  LangGraph usada.
- **Ventana controlada**: el historial que viaja al prompt se limita a las últimas
  `N` interacciones (N = 10 como valor inicial, `TODO(verify)`).
- **Resumen**: al superar el límite, un paso de resumen con un LLM barato condensa
  el historial descartado. Ese paso **solo resume**: no decide, no aplica reglas de
  negocio ni escribe en la memoria a largo plazo.

## Memoria a largo plazo (nivel 2)

En AgentCore Memory se guardan preferencias y hechos estables del cliente:

- Preferencias de producto o de canal, recordar si el cliente pidió notificaciones.
- Hechos declarados ("soy de Sahagún", "prefiero cita por la mañana").
- Resumen de episodios anteriores relevantes.

**Nunca** precios, stock, estados de pedido, horas ni nada transaccional: eso
puede quedar obsoleto y la memoria no es fuente de verdad. Escritura solo en
eventos relevantes; lectura vía tool con autorización por tenant. Mecanismos
exactos de AgentCore Memory (retención, tipos de memoria, APIs): `TODO(verify)`.

## Datos de negocio (nivel 3)

Siempre desde el backend legacy mediante tools en `src/adapters/legacy_backend/`:

- Cada tool: schema de entrada/salida, validación, autorización por `tenant_id`,
  timeout, idempotencia y log.
- El LLM no accede directo a la BD; si una tool falla, se responde con
  `fallback` y se marca el error, nunca con un valor inventado.

### Qué va y qué no va en cada nivel

| Dato | Nivel permitido | Por qué |
|---|---|---|
| "Prefiero cita en la mañana" | Memoria largo plazo | Preferencia estable |
| Últimos 10 mensajes del turno | Conversation state | Efímero, se resume |
| Precio, stock, disponibilidad | Solo legacy (nivel 3) | Puede cambiar en cualquier momento |
| Estado de un pedido | Solo legacy (nivel 3) | Transaccional |
| Resumen de episodio previo | Conversation state / largo plazo | Derivado, no operacional |

Conflictos: si un nivel 1 o 2 contradice al nivel 3, **gana el nivel 3** y el
contenido obsoleto de la memoria se marca para no reutilizarlo en el prompt.

## Tool `get_customer_context`

| Aspecto | Detalle |
|---|---|
| Qué devuelve | Identidad y estado del cliente en el tenant actual (nombre, pedidos/citas recientes relevantes, flags), sin PII innecesaria |
| Cuándo se llama | **Cada turno**, antes de invocar el prompt del especialista |
| Quién la actualiza | El orquestador, en eventos relevantes: pedido creado, cita agendada, cambio de estado |
| Autorización | Siempre filtrada por `tenant_id`; jamás cruza tenants |
| Fallo | Si falla, el turno continúa con contexto vacío + warning, o se responde `fallback` si el prompt lo exige |

## Regla: contexto obligatorio en cada turno

Cada turno debe incluir:

- **(a)** contexto del cliente vía `get_customer_context`.
- **(b)** historial con ventana controlada (y resumen si aplica).

Existe un test en `tests/agent_evals/` que **falla si el prompt llega sin ambos
bloques** (ver [EVALUATION.md](EVALUATION.md), caso "contexto ausente"). También
hay validación de contrato del modelo de prompt: las variables de contexto y
historial son requeridas en el modelo Pydantic de entrada.

## Flujo de un turno

```text
1. Mensaje del canal
      |
2. conversation_gateway: correlación, rate limit, correlation_id
      |
3. supervisor: clasifica intención (greeting/smalltalk -> ruta propia, sin tools)
      |
4. get_customer_context (obligatorio, por tenant)
      |
5. historial: ultimas N=10 interacciones; si se excede -> paso de resumen (LLM barato)
      |
6. Ruta elegida:
      - greeting/smalltalk -> prompt {tenant}/greeting (saludo neutral, sin ventas)
      - otra intencion     -> RAG (chunks) + tools de dominio (legacy)
      |
7. Guardrails (grounding + filtros + PII) sobre la respuesta candidata
      |
8. Comprehend (sentimiento) + reglas -> si se supera umbral:
      handoff, el bot deja de responder, notifica y marca human_takeover
      |
9. Persistencia: checkpointer/DynamoDB + escritura de eventos a memoria
      |
10. Respuesta al canal (con correlation_id en todos los logs)
```

Si en el paso 4 no hay contexto, el paso 6 debe degradar explícitamente y no
presentar datos del cliente como si existieran.
