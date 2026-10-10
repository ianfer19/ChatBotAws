output "function_names" {
  description = "Mapa nombre lógico → nombre real de cada Lambda en AWS."
  value       = { for nombre, fn in aws_lambda_function.this : nombre => fn.function_name }
}

output "invoke_arns" {
  description = "Mapa nombre lógico → invoke_arn (integración del módulo apigw)."
  value       = { for nombre, fn in aws_lambda_function.this : nombre => fn.invoke_arn }
}
