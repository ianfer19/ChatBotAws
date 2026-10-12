variable "aws_region" {
  description = "Región AWS del entorno; debe coincidir con la `region` de backend.hcl."
  type        = string
  default     = "us-east-1"
}

variable "webhook_verify_token" {
  description = "Token de verificación del webhook Meta (`hub.verify_token` del GET /webhook). TODO(verify): en prod, SSM SecureString/Secrets Manager (mismo criterio que los tokens de canal del legacy); hoy se pasa como variable sensible para no bloquear el despliegue inicial."
  type        = string
  sensitive   = true
  default     = ""
}

variable "meta_app_secret" {
  description = "Secreto de la app Meta para validar `X-Hub-Signature-256` en el POST /webhook. TODO(verify): en prod, SSM SecureString/Secrets Manager."
  type        = string
  sensitive   = true
  default     = ""
}
