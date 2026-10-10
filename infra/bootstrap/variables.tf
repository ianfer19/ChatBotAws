variable "aws_region" {
  description = "Región del bucket de estado y la tabla de lock; debe coincidir con la `region` de los backend.hcl de envs/."
  type        = string
  default     = "us-east-1"
}
