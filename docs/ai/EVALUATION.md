# Evaluación

Estrategia de evals de ChatBotAws: qué se mide, con qué dataset, con qué umbrales y
cuándo se ejecuta. La implementación concreta se entrega en la **Fase 9** (evals +
observabilidad).

## Tipos de evaluación

| Tipo | Qué cubre | Dónde vive |
|---|---|---|
| Unitarias de dominio | Reglas de negocio (`Order`, `Appointment`, validaciones) | `tests/unit/` |
| Contract de tools | Schemas, autorización por `tenant_id`, idempotencia, errores | `tests/contract/` |
| Evals de agente con datasets | Comportamiento punta a punta del orquestador | `tests/agent_evals/` |
| Regresión de prompts | Ningún cambio de plantilla degrada comportamiento | `tests/agent_evals/datasets/` |

Las regresiones de prompts se ejecutan ante **cualquier** cambio en `prompts/` o en
la versión publicada de Prompt Management (ver
[PROMPT_MANAGEMENT.md](PROMPT_MANAGEMENT.md)).

## Dataset

Ubicación: `tests/agent_evals/datasets/` (formato propuesto JSON; YAML aceptado).
Campos por caso:

```json
{
  "id": "greeting-001",
  "entrada": "Hola, ¿me ayudan?",
  "contexto_tenant": { "tenant_id": "comercio-demo", "canal": "whatsapp" },
  "esperado": {
    "intent": "greeting",
    "respuesta_coincide_con": "Buenas, bienvenido a {comercio}",
    "tools_invocadas": [],
    "human_takeover": false
  },
  "categoria": "greeting"
}
```

| Campo | Descripción |
|---|---|
| `id` | Identificador estable y único |
| `entrada` | Mensaje del usuario |
| `contexto_tenant` | Tenant, canal y estado mínimo para reproducir el turno |
| `esperado` | Intención, texto/regex esperado, tools invocadas, flags (`human_takeover`) |
| `categoria` | Agrupación para correr subconjuntos (`greeting`, `guardrails`, `handoff`, ...) |

El dataset se versiona como código: cambios de `esperado` requieren PR y revisión
igual que un cambio de prompt.

## Casos obligatorios

Cada release debe pasar estos cinco; el dataset completo los incluye:

| # | Caso | Esperado |
|---|---|---|
| 1 | **Saludo** | Responde saludo neutral ("Buenas, bienvenido a {comercio}, ¿en qué te ayudo?") con `intent = greeting` y **NO** invoca tools de ventas ni enruta a `sales` |
| 2 | **Contexto ausente** | **Falla** si el prompt llega sin `customer_context` ni historial: la eval construye el turno sin ambos y exige el error/flag de contrato |
| 3 | **Guardrails** | Respuesta no fundamentada (fuente insuficiente) => bloqueada, `fallback` del tenant, log con `correlation_id` |
| 4 | **Handoff** | Mensaje con enojo evidente => `human_takeover = true` y el bot deja de responder |
| 5 | **Aislamiento de tenant** | La respuesta **no** filtra datos de otro `tenant_id` (incluye chunks, contexto y prompts) |

## Métricas

| Métrica | Definición | Umbral inicial |
|---|---|---|
| Task success | % de casos con resultado esperado | `TODO(verify)` (p. ej. >= 0.95) |
| Grounding score | Promedio de la señal de contextual grounding | >= umbral de [GUARDRAILS.md](GUARDRAILS.md) (`TODO(verify)`) |
| Tasa de handoff | % de turnos que terminan en `human_takeover` | `TODO(verify)`; alerta si se dispara |
| Falsos positivos de abuso | Usuarios legítimos bloqueados | `TODO(verify)`; calibrar por heurística |
| Latencia p50/p95 por turno | De ingreso a respuesta | `TODO(verify pricing)`/presupuesto `TODO(verify)` |

## Cuándo se ejecutan

| Trigger | Alcance | Cadencia |
|---|---|---|
| CI (pull request) | Unitarias + contract + subconjunto ligero del dataset (smoke) | Cada PR |
| Cambio de prompt / versión publicada | Regresión completa de prompts | Cada PR que toca `prompts/` |
| Nocturnas | Dataset completo + evals de agente | Programado |
| Release | Casos obligatorios + métricas | Antes de promover a prod |

El pipeline nocturno publica resultados y alerta cuando una métrica cae por debajo
de su umbral. Los umbrales viven en configuración, no hardcodeados en el dataset.

## Umbral de aceptación y versionado del dataset

- **Aceptación**: una versión de prompt/modelo solo se promueve si todos los casos
  obligatorios pasan y `task success` y `grounding score` cumplen su umbral.
  Cualquier fallo detiene el rollout (etapa 3 del flujo de
  [PROMPT_MANAGEMENT.md](PROMPT_MANAGEMENT.md)).
- **Versionado del dataset**: el dataset se trata como artefacto versionado; se
  le agrega un identificador de versión (p. ej. `datasets/v1/` o campo `dataset_version`)
  y los resultados de cada corrida guardan esa versión para poder comparar.
- **Actualización de casos**: agregar casos es un PR; modificar el `esperado` de un
  caso existente requiere justificación y revisión del dueño del comportamiento
  afectado.
- **Cobertura mínima**: por cada regla de negocio nueva en `domain/`, al menos un
  caso de dataset; por cada prompt nuevo, su regresión.

## Alineación con la Fase 9

La Fase 9 (evals + observabilidad) implementa:

1. Runner de evals y publicación de resultados (`tests/agent_evals/`).
2. Suite nocturna y gate por cambio de prompt en CI.
3. Métricas de negocio y de calidad (task success, grounding, handoff, abuso,
   latencia) con alertas.
4. Calibración de umbrales de guardrails y de abuso con datos reales
   (ver [GUARDRAILS.md](GUARDRAILS.md)).

Referencias: [../adr/0008-contextual-grounding-en-chatbot.md](../adr/0008-contextual-grounding-en-chatbot.md),
[../../AGENTS.md](../../AGENTS.md).
