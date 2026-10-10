output "bucket_name" {
  description = "Nombre del bucket de archivo del entorno."
  value       = aws_s3_bucket.archivo.id
}

output "bucket_arn" {
  description = "ARN del bucket de archivo (para políticas IAM por prefijo de tenant)."
  value       = aws_s3_bucket.archivo.arn
}
