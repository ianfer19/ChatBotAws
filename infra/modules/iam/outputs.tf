output "role_arns" {
  description = "Mapa función lógica → ARN de su rol IAM (para el módulo lambda de la Fase 4)."
  value       = { for nombre, rol in aws_iam_role.lambda : nombre => rol.arn }
}
