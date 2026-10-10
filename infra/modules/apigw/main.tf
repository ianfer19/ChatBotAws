# API Gateway HTTP (v2) del entorno: punto de entrada público del sistema.
#
# Hoy expone el webhook de Meta (`GET /webhook` para la verificación
# `hub.challenge` y `POST /webhook` para los mensajes; el chequeo de firma
# ocurre dentro de la Lambda, Paso 9). Rutas internas y rate limiting llegan
# con el Paso 9 → TODO(verify). Access logs en JSON con `$context` para poder
# filtrarlos por `requestId`/`routeKey` en CloudWatch.

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/apigateway/${var.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.this.arn
    format = jsonencode({
      requestId               = "$context.requestId"
      sourceIp                = "$context.identity.sourceIp"
      requestTime             = "$context.requestTime"
      httpMethod              = "$context.httpMethod"
      routeKey                = "$context.routeKey"
      status                  = "$context.status"
      protocol                = "$context.protocol"
      responseLength          = "$context.responseLength"
      integrationErrorMessage = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_apigatewayv2_integration" "this" {
  for_each = var.routes

  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.functions[each.value.function]
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "this" {
  for_each = var.routes

  api_id    = aws_apigatewayv2_api.this.id
  route_key = "${each.value.method} ${each.value.path}"
  target    = "integrations/${aws_apigatewayv2_integration.this[each.key].id}"
}

# Permiso concreto por ruta (no `*`): solo las rutas declaradas aquí pueden
# invocar esa Lambda desde esta API.
resource "aws_lambda_permission" "this" {
  for_each = var.routes

  statement_id  = "AllowInvoke-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = "chatbot-aws-${var.environment}-${each.value.function}"
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/${each.value.method}/${trimprefix(each.value.path, "/")}"
}
