variable "name_prefix" {
  description = "Prefijo del bucket (p. ej. `chatbot-aws-dev-archivo`); se le añade el id de cuenta para unicidad global."
  type        = string
}

variable "kms_key_arn" {
  description = "ARN de la llave KMS del entorno para cifrar los objetos; `null` usa la llave gestionada por S3 (`aws/s3`)."
  type        = string
  default     = null
}
