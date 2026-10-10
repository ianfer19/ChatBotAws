# Tests de agente (evals)

Evaluaciones de **comportamiento conversacional** que no son unitarias ni de contrato:
comprueban lo que el agente responde y hace en situaciones concretas.

## Estructura

```
tests/agent_evals/
├── README.md          # este archivo
├── datasets/          # casos versionados (JSON) — ver docs/ai/EVALUATION.md
│   ├── supervisor_routing.json       # enrutado del supervisor (Paso 4)
│   ├── appointments_behavior.json    # comportamiento de citas (Paso 5)
│   ├── orders_behavior.json          # comportamiento de pedidos (Paso 5)
│   └── faq_behavior.json             # comportamiento del agente faq (Paso 7)
└── test_<nombre>.py   # ejecutores de los datasets (Paso 4, 5 y 7 con LLM doble;
                       #   modelo real en el Paso 14)
```

## Casos obligatorios (regresión)

| ID | Caso | Esperado |
|---|---|---|
| `greeting_01` | El usuario solo saluda | Saludo neutral del supervisor; **no** enruta a ventas ni invoca tools |
| `context_01` | Turno construido sin contexto de cliente ni historial | **Falla** el test (requisito de contexto obligatorio) |
| `grounding_01` | Pregunta sin respaldo en el conocimiento | Fallback honesto o bloqueo del guardrail; nunca inventar |
| `handoff_01` | Mensaje con enojo alto | `human_takeover`; el bot deja de responder |
| `tenant_isolation_01` | Petición con datos de otro tenant | La respuesta jamás filtra datos de otro comercio |
| `order_time_01` | "Cambia la hora de mi pedido" | Rechazo en dominio; no existe la tool; sin invocaciones |

## Convenciones

- Los datasets son **sintéticos** (nunca datos reales de clientes).
- Cada caso: `id`, `entrada`, `tenant` de prueba, `esperado`, `categoría`.
- Un cambio de prompt no puede mergearse si un caso obligatorio pasa a fallar
  (ver `docs/ai/EVALUATION.md`).

Estado: `datasets/supervisor_routing.json` + su ejecutor existen desde el **Paso 4**
(regresión de saludo y enrutado); `orders_behavior.json` y `appointments_behavior.json`
+ sus ejecutores desde el **Paso 5** (regla crítica de la hora, política `AUTO`/`CONFIRM`
y «sin hora → pide el dato»), todos con LLM doble. `faq_behavior.json` + su ejecutor
existen desde el **Paso 7** y cubren `grounding_01` (fuera del conocimiento → fallback
honesto sin invención), la respuesta con la fuente citada y `tenant_isolation_01` (la
misma pregunta solo ve los chunks del propio comercio). Los casos anteriores sin
dataset (`context_01`, `handoff_01`) ya están definidos aquí como contrato; los
ejecutores con modelo real llegan en el **Paso 14**.
