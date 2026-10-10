variable "environment" {
  description = "Entorno que posee las funciones; aparece en el nombre de cada una."
  type        = string
}

variable "functions" {
  description = <<-EOT
    Mapa nombre lógico → configuración de cada Lambda Python 3.12.
    `zip_path` apunta al artefacto empaquetado (gitignorado, ver
    artifacts/README.md); `env` son las variables que lee `shared/config`
    (prefijo CHATBOT_).
  EOT
  type = map(object({
    handler     = string
    zip_path    = string
    timeout     = optional(number, 10)
    memory_size = optional(number, 256)
    env         = optional(map(string), {})
  }))
  nullable = false
}

variable "role_arns" {
  description = "Mapa nombre lógico → ARN del rol IAM de esa función (salida del módulo iam)."
  type        = map(string)
  nullable    = false
}

variable "log_retention_days" {
  description = "Días de retención de los logs de cada Lambda en CloudWatch."
  type        = number
  default     = 14
}
