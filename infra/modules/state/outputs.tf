output "bucket_name" {
  description = "Nombre del bucket S3 que alberga los states de todos los entornos."
  value       = aws_s3_bucket.state.id
}

output "bucket_arn" {
  description = "ARN del bucket de estado (para políticas IAM que lo referencien)."
  value       = aws_s3_bucket.state.arn
}

output "lock_table_name" {
  description = "Nombre de la tabla DynamoDB usada como lock por los backends S3."
  value       = aws_dynamodb_table.lock.name
}
