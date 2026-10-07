# Guardrails

Defensa en capas de ChatBotAws. Los guardrails de Amazon Bedrock son **una** capa
(más una), no la única: no sustituyen validación en dominio ni autorización en
tools.

## Mapa de defensa en capas

Ejemplo canónico: el chatbot **no** puede modificar la hora de un pedido.

| # | Capa | Qué falla si esta capa no existiera |
|---|---|---|
| 1 | Tool inexistente para el LLM | El modelo podría "inventar" la operación y llamarla |
| 2 | Dominio `Order` rechaza | Una tool mal expuesta igualmente no muta la hora |
| 3 | AgentCore Policy deniega | Autorización final independiente del modelo |
| 4 | Tema denegado en Guardrails | Se bloquea antes de generar la respuesta |
| 5 | Test de regresión | Cualquier rotura de las capas anteriores falla en CI |

Detalle de cada capa en la sección [Qué regla se defiende en qué capa](#qué-regla-se-defiende-en-qué-capa)
y en [RAG.md](RAG.md) / [MEMORY_AND_CONTEXT.md](MEMORY_AND_CONTEXT.md) para el
acceso a datos.

## Bedrock Guardrails: filtros de contenido

Categorías (violencia, sexual, odio, insulto, conducta inapropiada, ataque al
prompt) con nivel de fortaleza. Fortaleza y categorías exactas: `TODO(verify)`
contra la documentación vigente.

| Fortaleza | Efecto típico | Cuándo usarlo |
|---|---|---|
| `NONE` | Sin filtro | No se usa en prod |
| `LOW` | Bloqueo solo evidente | Si hay muchos falsos positivos |
| `MEDIUM` | Balanceado | Valor inicial propuesto |
| `HIGH` | Sensible | Canales públicos o alto riesgo |

## Temas denegados (denied topics)

Aplica cuando una **intención completa** no debe generarse. Ejemplos para este
proyecto:

- "modificar la hora de un pedido" -> se bloquea (el sistema solo consulta estado).
- "reembolsar o cancelar pedidos sin verificación" -> se bloquea.
- pedir credenciales, datos de otros clientes o internals del sistema -> se bloquea.

Mensaje al bloquear: se responde con el prompt `fallback` del tenant (ver
[PROMPT_MANAGEMENT.md](PROMPT_MANAGEMENT.md)), nunca con el motivo interno.

## Palabras y expresiones (word/regex filters)

Filtros léxicos y por expresión regular para:

- Palabras ofensivas o de contenido denegado.
- Patrones de secretos (`AKIA...`, `Bearer <token>`) que no deben aparecer ni en
  entrada ni en salida.
- Firmas de prompt injection más comunes ("ignora las instrucciones anteriores",
  "actúa como sistema"). Es un filtro barato, no una defensa completa: la
  inyección sofisticada la cubren instruction hierarchy, sandwich defense y
  canary tokens (ver [PROMPT_ENGINEERING.md](PROMPT_ENGINEERING.md)).

## PII: anonymize vs block

| Modo | Efecto | Uso recomendado |
|---|---|---|
| `anonymize` | Reemplaza la PII detectada y conserva el flujo | Entrada del usuario (no rompe la conversación) |
| `block` | Detiene la operación | Salida del modelo si expone PII de terceros |

`TODO(verify)` de los tipos de PII soportados en español y del comportamiento
exacto de anonymize en el canal de salida.

## Contextual grounding check

Ver [../adr/0008-contextual-grounding-en-chatbot.md](../adr/0008-contextual-grounding-en-chatbot.md).

### Qué mide

| Señal | Rango | Significado |
|---|---|---|
| `grounding` | 0 a 0.99 | Cuánto de la respuesta está respaldado por la fuente |
| `relevance` | 0 a 0.99 | Qué tan pertinente es la respuesta a la consulta dada la fuente |

Semántica exacta de ambos calificadores: `TODO(verify)` contra la documentación
vigente de AWS.

### Las tres entradas

| Entrada | Qué se pasa |
|---|---|
| `grounding_source` | Chunks recuperados por RAG (ver [RAG.md](RAG.md)) |
| `query` | Pregunta del cliente |
| `guard_content` | Respuesta candidata generada por el LLM |

### Cómo se pasan

**Con `Converse` (calificadores):** el guardrail se configura en la invocación con
el id y versión del guardrail más los calificadores de contextual grounding.
`TODO(verify)` de los nombres exactos de parámetros y de la forma de declarar
`grounding_source`, `query` y `guard_content` en la petición.

**Con `ApplyGuardrail`:** permite aplicar el guardrail **sin invocar un modelo**;
recibe el id/versión del guardrail, la fuente, la consulta y el contenido a
evaluar, y devuelve la decisión y las evaluaciones. `TODO(verify)` de los nombres
exactos de operación y de parámetros, y de la verificación de que las tres
entradas estén soportadas en esta vía.

### Umbrales

Rango válido: 0 a 0.99 (no se puede pedir 1). Valores iniciales propuestos:

| Señal | Umbral inicial | Nota |
|---|---|---|
| `grounding` | 0.80 | Respuestas con respaldo débil se bloquean |
| `relevance` | 0.70 | Evita responder por approximación |

`TODO(verify)` de estos valores: calibrarlos con el dataset de evals
([EVALUATION.md](EVALUATION.md)) y ajustar por tasa de falsos positivos.

### Limitación documentada de AWS

La documentación de AWS **no** declara explícitamente el caso "chatbot / QA
conversacional" como soportado para contextual grounding: verificar vigencia y
alcance (idiomas, formatos, canales) antes de depender de esta capa.
`TODO(verify)`.

### Comportamiento al bloquear

1. Responder con el mensaje `fallback` del tenant (nada de detalles internos).
2. Log estructurado: `correlation_id`, `tenant_id`, `prompt_kind`, `scores`
   (grounding/relevance o categoría de filtro), `rule_triggered`, `latency_ms`.
3. Métrica de bloqueos (contador por `tenant_id` y tipo de regla) para alertas y
   para calibrar umbrales.
4. Marcar el turno como bloqueado en la conversación para poder auditarlo.

## Qué regla se defiende en qué capa

Regla: **el chatbot no puede modificar la hora de un pedido.**

| Capa | Mecanismo | Qué hace |
|---|---|---|
| 1. Tools | No existe tool de reprogramación de hora | El LLM no puede siquiera invocarla |
| 2. Dominio | `Order` rechaza la mutación de hora | Falla incluso si alguien la expone |
| 3. AgentCore Policy | Denegación explícita de esa acción por identidad | Autorización independiente del modelo |
| 4. Guardrails | Tema denegado "modificar hora de pedido" | Bloquea generación + log + fallback |
| 5. Tests | Caso de regresión en `tests/agent_evals/datasets/` | Cualquier rotura falla en CI |

## Qué NO resuelven los guardrails

- **Precios, stock, disponibilidad, estados de pedido y horas**: siguen siendo
  trabajo de tools y del dominio; un guardrail no valida datos.
- **Autorización y aislamiento de tenant**: es responsabilidad de tools
  (validación por `tenant_id`), Policy y pruebas de contrato.
- **Parámetros de tools**: schema, tipos, rangos e idempotencia se validan en
  `application/` y en `domain/`.
- **Prompt injection sofisticada y leaking**: requieren sandwich defense, canary
  tokens y evals (ver [PROMPT_ENGINEERING.md](PROMPT_ENGINEERING.md)).
- **Abuso y rate limiting**: vive en el slice `abuse_protection` con heurísticas
  baratas primero y clasificador LLM solo si hace falta.

Si una regla solo vive en el guardrail, está mal implementada: debe existir
también en dominio, en Policy y en un test.
