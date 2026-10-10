output "api_endpoint" {
  description = "Endpoint base de la API HTTP (para configurar la URL de callback en Meta)."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "api_id" {
  description = "ID de la API HTTP (para recursos futuros y runbooks)."
  value       = aws_apigatewayv2_api.this.id
}
