variable "aws_region" {
  description = "Región AWS del entorno; debe coincidir con la `region` de backend.hcl."
  type        = string
  default     = "us-east-1"
}
