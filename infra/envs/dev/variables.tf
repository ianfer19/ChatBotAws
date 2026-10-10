variable "aws_region" {
  description = "Región AWS del entorno; debe coincidir con la `region` de backend.hcl."
  type        = string
  default     = "us-east-1"
}

variable "admin_token" {
  description = "Token propio mínimo del endpoint `POST /admin/channels` (decisión 6 del Paso 9). `TODO(verify)`: inyectarlo desde Secrets Manager/SSM en prod, sin pasar por el estado."
  type        = string
  sensitive   = true
  default     = ""
}
