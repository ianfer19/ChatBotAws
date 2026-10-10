output "archivo_bucket" {
  description = "Bucket de archivo de conversaciones y media del entorno."
  value       = module.s3.bucket_name
}

output "tablas" {
  description = "Tablas DynamoDB operacionales del entorno (nombre lógico → real)."
  value       = module.dynamodb.table_names
}

output "vpc_id" {
  description = "VPC del entorno (red mínima, subnets privadas)."
  value       = module.network.vpc_id
}

output "aurora_endpoint" {
  description = "Endpoint de escritura de Aurora (conocimiento RAG, Paso 7)."
  value       = module.aurora.cluster_endpoint
}
