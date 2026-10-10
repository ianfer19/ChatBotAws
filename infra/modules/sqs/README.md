# Módulo: sqs

Cola de eventos del `conversation_gateway` (Paso 9) con **DLQ** detrás: el webhook
publica `inbound.message` y el consumer (Fase 6) lo procesa con
`batchItemFailures`. **Paso 9.**

## Recursos

- `aws_sqs_queue` principal: long polling (sin recibir en vacío), retención de
  4 días, cifrado SSE (llave del entorno cuando se pasa) y `redrive_policy`
  hacia la DLQ tras `max_receive_count` recibos fallidos.
- `aws_sqs_queue` DLQ con retención de 14 días (máximo) para inspección manual
  de mensajes tóxicos.

## Variables

| Nombre | Descripción |
| --- | --- |
| `name_prefix` | Prefijo de nombres del entorno (p. ej. `chatbot-aws-dev`). |
| `kms_key_arn` | Llave del entorno (entra como `kms_master_key_id`; `null` = SSE de SQS). |
| `visibility_timeout_seconds` | Ocultación durante el procesamiento (≥ timeout del consumer, `TODO(verify)` en Fase 6). |
| `max_receive_count` | Recibos fallidos antes de ir a la DLQ (por defecto 3). |
| `events_message_retention_seconds` | Retención en la cola principal (por defecto 4 días). |
| `dlq_message_retention_seconds` | Retención en la DLQ (por defecto 14 días). |
| `long_polling_seconds` | Segundos de long polling (0–20, por defecto 10). |

## Salidas

`queue_url` (envío; la usa la Lambda del webhook), `queue_arn` (permisos),
`dlq_url` y `dlq_arn` (inspección y alertas).
