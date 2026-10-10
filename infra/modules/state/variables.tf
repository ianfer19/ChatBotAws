variable "bucket_name" {
  description = "Nombre S3 globalmente único del bucket que guarda el estado de Terraform."
  type        = string
}

variable "lock_table_name" {
  description = "Nombre de la tabla DynamoDB que hace de lock para los backends S3."
  type        = string
}
