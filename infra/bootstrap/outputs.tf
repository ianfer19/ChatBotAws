output "state_bucket_name" {
  description = "Bucket S3 creado; debe coincidir con el `bucket` de envs/*/backend.hcl."
  value       = module.state.bucket_name
}

output "lock_table_name" {
  description = "Tabla DynamoDB de lock creada; debe coincidir con el `dynamodb_table` de envs/*/backend.hcl."
  value       = module.state.lock_table_name
}
