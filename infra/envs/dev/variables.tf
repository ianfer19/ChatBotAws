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

variable "webhook_verify_token" {
  description = "Token de verificación del webhook Meta (`hub.verify_token` del GET /webhook). `TODO(verify)`: en prod, SSM SecureString/Secrets Manager (mismo criterio que los tokens de canal del legacy)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "meta_app_secret" {
  description = "Secreto de la app Meta para validar `X-Hub-Signature-256` en el POST /webhook. `TODO(verify)`: en prod, SSM SecureString/Secrets Manager."
  type        = string
  sensitive   = true
  default     = ""
}
