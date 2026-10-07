# Slice: supervisor

> Fase de implementación: **Fase 4**. Estado: **definido, sin implementar**. Router de
> intención de todos los turnos.

## Responsabilidad

Recibe el mensaje normalizado del gateway, decide la intención (`greeting`/`smalltalk`,
`sales`, `appointments`, `orders`, `faq`) y enruta al agente/especialista adecuado — o
responde él mismo en el caso del saludo. Aplica también la salida temprana de handoff
(`sentiment_handoff`) y la de abuso (`abuse_protection`). NO ejecuta tools de negocio.

## Entradas y salidas

- Entradas: contrato `InboundMessage` (con `tenant_id` y `correlation_id` ya resueltos).
- Salidas: respuesta directa (saludo) o enrutado a un agente (contrato en
  `shared/contracts/`); intención clasificada registrada para métricas/evals.

## Ports

- Expone: contrato `RoutedTurn` (mensaje + intención + agente destino).
- Consume: `LLMPort` (`shared/ports/`, implementado en `adapters/bedrock`), puerto de
  prompts (`tenant_prompts`), contratos de salida de `sentiment_handoff` y
  `abuse_protection`.

## Tablas y recursos AWS

| Recurso | Por qué | Fase |
|---|---|---|
| Bedrock (modelo clasificador) | Decisión de intención barata y configurable | 4 |
| Prompt `supervisor` (Prompt Management) | Clasificación versionada por tenant | 5 |
| DynamoDB (métrica de intenciones, opcional) | Dashboards de uso por tenant | 4/9 |

## Reglas de negocio clave

1. **El saludo tiene ruta propia**: intención `greeting`/`smalltalk` → respuesta neutral
   propia del supervisor ("Buenas, bienvenido a {comercio}, ¿en qué te ayudo?") usando solo
   el nombre/branding del contexto del tenant; **jamás** se enruta a ventas (requisito de
   regresión: test obligatorio).
2. La clasificación es una **decisión de orquestación**, no una regla de negocio: el
   prompt solo clasifica; el enrutado vive en código (`application/`).
3. Todo turno pasa primero por `abuse_protection` y `sentiment_handoff`: si alguno marca
   salida (`blocked` o `human_takeover`), el supervisor no invoca agentes.
4. Intención desconocida o baja confianza → ruta `faq`/`smalltalk` con respuesta honesta;
   nunca inventar (ver `knowledge_rag` y ADR 0008).
5. `allowed_bots` del tenant restringe las rutas disponibles (p. ej. comercio sin citas →
   nunca enruta a `appointments`).

## Tools expuestas al LLM

Ninguna de negocio. El supervisor solo usa el prompt de clasificación (sin tools) o
responde con el saludo plantilla del tenant.

## Errores esperados

| Error | Cuándo | Traducción |
|---|---|---|
| `AmbiguousIntentError` | Confianza por debajo del umbral `TODO(verify)` | Ruta segura `faq`/saludo |
| `IntentNotAllowedByTenant` | Intención válida pero no en `allowed_bots` | Mensaje "ese servicio aún no está disponible" |
| Fallo de `LLMPort` | Bedrock caído | Fallback a enrutado por palabras clave + log |

## Cómo probarlo

- Unit (`tests/unit/`): tabla de casos intención→ruta; saludo → `greeting` y nunca
  `sales`; `allowed_bots` restringe rutas.
- Eval (`tests/agent_evals/datasets/`): **caso obligatorio de saludo** (requisito 7.2) y
  casos de ambigüedad; falla el build si el saludo enruta a ventas.
- Contract: el `RoutedTurn` siempre lleva `tenant_id`/`correlation_id`.
