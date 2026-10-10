output "key_arn" {
  description = "ARN de la llave KMS del entorno (para cifrar tablas, buckets y Aurora)."
  value       = aws_kms_key.this.arn
}

output "key_id" {
  description = "ID de la llave KMS del entorno."
  value       = aws_kms_key.this.key_id
}
