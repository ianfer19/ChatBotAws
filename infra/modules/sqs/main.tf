# Cola de entrada del conversation gateway (Paso 9) con DLQ detrás: el webhook
# solo publica `inbound.message` y el consumer (Fase 6) procesa con
# `batchItemFailures`. Long polling (sin polling en vacío) y cifrado en reposo
# con la llave del entorno cuando se pasa.
#
# `max_receive_count` mueve a la DLQ los mensajes tóxicos para inspección
# manual; TODO(verify): afinar visibilidad/retención con el timeout real del
# consumer cuando exista (Fase 6). La llave del entorno entra por
# `kms_master_key_id` (provider aws < 6; `kms_key_arn` no existe aquí).

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name_prefix}-events-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds
  sqs_managed_sse_enabled   = var.kms_key_arn == null
  kms_master_key_id         = var.kms_key_arn
}

resource "aws_sqs_queue" "events" {
  name                       = "${var.name_prefix}-events"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.events_message_retention_seconds
  receive_wait_time_seconds  = var.long_polling_seconds
  sqs_managed_sse_enabled    = var.kms_key_arn == null
  kms_master_key_id          = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}
