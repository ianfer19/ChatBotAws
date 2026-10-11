# Lambdas del entorno: una por punto de entrada (gateway y orquestador),
# rol IAM propio por función (módulo iam) y grupo de logs con retención
# explícita — sin ella los logs se guardan para siempre y la factura crece
# sin control.
#
# El zip todavía no existe en el repo (artifacts/ está gitignorado): por eso
# `source_code_hash` envuelve `filebase64sha256` en `try()` para que
# `validate` y CI pasen sin artefacto. Al APLICAR sí debe existir el zip →
# TODO(verify): empaquetado por slice (Paso 9).

resource "aws_cloudwatch_log_group" "this" {
  for_each = var.functions

  name              = "/aws/lambda/chatbot-aws-${var.environment}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  for_each = var.functions

  function_name    = "chatbot-aws-${var.environment}-${each.key}"
  role             = var.role_arns[each.key]
  handler          = each.value.handler
  runtime          = "python3.12"
  filename         = each.value.zip_path
  source_code_hash = try(filebase64sha256(each.value.zip_path), null)
  timeout          = each.value.timeout
  memory_size      = each.value.memory_size

  environment {
    variables = each.value.env
  }

  # El grupo de logs debe existir antes que la función: si Lambda lo crea él
  # primero, quedaría sin retención configurada.
  depends_on = [aws_cloudwatch_log_group.this]
}

# Consumo de la cola SQS (Fase 6): solo las funciones listadas en
# `event_source_arns` (p. ej. `consumer`) reciben un mapping. El rol de la
# función necesita `sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes`
# (módulo iam); `ReportBatchItemFailures` hace que el consumer pueda acusar
# mensajes individuales con `batchItemFailures` (reintento puntual).
resource "aws_lambda_event_source_mapping" "sqs" {
  for_each = var.event_source_arns

  event_source_arn        = each.value
  function_name           = aws_lambda_function.this[each.key].arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}
