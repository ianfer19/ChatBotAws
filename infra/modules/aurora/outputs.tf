output "cluster_endpoint" {
  description = "Endpoint del clúster Aurora (host del pool de escritura) para los adapters del Paso 7."
  value       = aws_rds_cluster.this.endpoint
}

output "cluster_id" {
  description = "Identificador del clúster Aurora."
  value       = aws_rds_cluster.this.id
}

output "master_secret_arn" {
  description = "ARN del secreto de Secrets Manager con las credenciales del master (gestionado por AWS)."
  value       = try(aws_rds_cluster.this.master_user_secret[0].secret_arn, null)
}
