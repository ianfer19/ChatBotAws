# Slice: sentiment_handoff

> Fase de implementación: **Fase 7**. Estado: **definido, sin implementar** (el detalle
> funcional se completa en su fase; este documento es el contrato previo).

## Responsabilidad
Detección de enojo y traspaso a humano: analiza el texto de cada turno, aplica las reglas
de negocio de sentimiento y, si se supera el umbral, marca la conversación en
`human_takeover`. No redacta respuestas, no decide otras intenciones y no notifica por
su cuenta al usuario final.

## Entradas y salidas
- Entradas: texto del turno desde el contrato de `conversation_gateway`
  (`../../../shared/contracts/`), ventana de los últimos N turnos y el contexto
  (`tenant_id`, `correlation_id`) resuelto en el gateway.
- Salidas: contrato de handoff con estado `human_takeover`; notificación al canal
  interno del legacy (WebSocket → TODO(verify)); registro de auditoría con motivo; y la
  señal para que el bot deje de responder.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): contrato `HandoffRequest` y
  estado `human_takeover` (TODO(decision): nombres finales).
- Consume: `SentimentPort` (implementado por `adapters/comprehend`), `NotificationPort`
  (canal interno del legacy → TODO(verify)) y ports del propio domain con los umbrales,
  la lista de palabras críticas y la ventana de reincidencia.

## Tablas y recursos AWS
| Recurso | Por qué | Fase |
|---|---|---|
| Amazon Comprehend (sentiment) | Clasificación del sentimiento de cada turno | 7 |
| DynamoDB (ventana de turnos, TTL) | Reincidencia en N turnos por número y tenant | 7 |
| CloudWatch Logs | Auditoría del handoff con motivo y `correlation_id` | 7 |

## Reglas de negocio clave
1. Umbrales y reglas (negatividad, reincidencia en N turnos, palabras críticas) viven en
   `domain/`, nunca en el prompt; los valores iniciales son TODO(decision).
2. La lista de palabras críticas se versiona en domain/config, no en el system prompt.
3. Si se supera la regla → la conversación pasa a `human_takeover` y el bot no responde
   en ese turno.
4. La notificación lleva motivo, `correlation_id` y un resumen de los últimos turnos sin
   PII.
5. Fallo de Comprehend → degradación a las reglas de palabras críticas + log warn.
6. Nunca se loguea el texto íntegro del turno ni PII completa del cliente.
7. Solo el humano levanta el takeover; el bot no se reactiva por su cuenta.

## Tools expuestas al LLM
— (no expone tools)

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `ComprehendUnavailable` | Comprehend falla o expira el timeout | Degradación a palabras críticas + log warn |
| `HandoffNotificationFailed` | No se pudo avisar al legacy | Takeover igualmente + reintento + log error |
| `MissingTurnContext` | Falta la ventana de N turnos | Se evalúa solo el turno actual + log warn |
| `NegativeSentimentBelowThreshold` | Sentimiento negativo pero bajo el umbral | Se responde normalmente + log debug |

## Cómo probarlo
- `tests/unit/`: domain de `sentiment_handoff` — umbral de negatividad, reincidencia en
  N turnos y degradación cuando Comprehend no responde.
- `tests/contract/`: esquema del contrato de handoff y que el turno lleva `tenant_id` y
  `correlation_id` del contexto, no del payload.
- `tests/agent_evals/datasets/`: mensaje furioso → takeover activo y sin respuesta del
  bot en el mismo turno; mensaje cordial → respuesta normal.
