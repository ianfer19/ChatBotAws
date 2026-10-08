# Slice: abuse_protection

> **Fuera de la ruta** (ROADMAP §4). Estado: **definido, sin implementar** (el detalle
> funcional se completa en su paso; este documento es el contrato previo).

## Responsabilidad
Bloqueo temporal por abuso: evalúa cada mensaje con heurísticas baratas primero y, solo
si hace falta, con un clasificador LLM; detecta gasto de tokens sin propósito comercial,
prompt injection/poisoning y tráfico de bots externos. No redacta respuestas, no decide
intención y no sustituye al guardrail general (`../../../docs/ai/GUARDRAILS.md`).

## Entradas y salidas
- Entradas: cada mensaje ya normalizado por `conversation_gateway` (número remitente,
  `tenant_id`, texto, firma y frecuencia del remitente) y métricas de consumo de tokens
  por número y por tenant.
- Salidas: decisión `allow`/`block` con TTL, motivo persistido en la tabla de auditoría,
  métricas en CloudWatch y ejecución del runbook de desbloqueo manual
  (`docs/runbooks/ABUSE_UNLOCK.md`).

## Ports
- Expone (aplicación a otros slices vía shared/contracts): contrato `AbuseDecision`
  (número, tenant, motivo, `expires_at`) con el que el gateway detiene el flujo
  (TODO(decision): nombre final).
- Consume: ports del domain (`RateLimitPort`, `ClassifierPort`), adapter
  `adapters/bedrock` (clasificador LLM solo si las heurísticas no bastan) y `ClockPort`
  para calcular el TTL del bloqueo.

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| DynamoDB `abuse_blocks` (TTL configurable) | Bloqueo temporal por número y tenant | fuera de ruta |
| DynamoDB `abuse_audit` | Motivo, umbral y decisión de cada bloqueo o desbloqueo | fuera de ruta |
| Bedrock (clasificador) | Injection/poisoning solo si las heurísticas no bastan | fuera de ruta |
| CloudWatch Logs/Metrics | Tasas por número, tenant y campaña para calibrar umbrales | fuera de ruta |

## Reglas de negocio clave
1. Heurísticas baratas primero: rate limit por número/tenant, patrones de texto y
   firma/frecuencia del remitente; el clasificador LLM entra solo si hace falta.
2. Se detectan: gasto de tokens sin propósito comercial, prompt injection/poisoning y
   tráfico de bots externos (p. ej. Tigo).
3. El bloqueo tiene TTL configurable y el motivo siempre queda en la auditoría.
4. El desbloqueo es manual y pasa por el runbook `docs/runbooks/ABUSE_UNLOCK.md`.
5. Umbrales iniciales y su calibración por falsos positivos: TODO(decision).
6. No se bloquea a clientes legítimos en campañas o picos: ventana de gracia por tenant.
7. Nunca se registra el payload completo sospechoso en logs: solo patrones, hash y
   metadatos.
8. NO expone tools al LLM.

## Tools expuestas al LLM
— (no expone tools)

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `RateLimitExceeded` | Supera el límite de mensajes por ventana | Bloqueo con mensaje genérico + log warn |
| `InjectionDetected` | Patrón de prompt injection o poisoning | Bloqueo inmediato + log warn sin eco del payload |
| `ClassifierUnavailable` | El clasificador LLM no responde | Decisión solo con heurísticas + log warn |
| `FalsePositiveSuspected` | Bloqueo durante campaña o pico | Revisión manual vía runbook + log info |

## Cómo probarlo
- `tests/unit/`: domain de `abuse_protection` — rate limit por número y tenant, TTL del
  bloqueo y degradación a solo heurísticas si el clasificador no está.
- `tests/contract/`: esquema de `AbuseDecision` (número, tenant, motivo, `expires_at`)
  sin PII adicional ni payload completo.
- `tests/agent_evals/datasets/`: caso de bloqueo correcto (inyección detectada) y caso
  límite documentado de falso positivo con su desbloqueo por runbook.
