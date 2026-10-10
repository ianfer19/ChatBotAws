variable "name_prefix" {
  description = "Prefijo común de los recursos del entorno (p. ej. `chatbot-aws-dev`)."
  type        = string
}

variable "kms_key_arn" {
  description = "ARN de la llave KMS del entorno; `null` usa el cifrado gestionado por SQS."
  type        = string
  default     = null
}

variable "visibility_timeout_seconds" {
  description = "Segundos que un mensaje queda oculto mientras el consumer lo procesa; debe ser >= timeout de la Lambda consumidora (Fase 6, TODO(verify))."
  type        = number
  default     = 60
}

variable "max_receive_count" {
  description = "Recibos fallidos de un mensaje antes de moverlo a la DLQ."
  type        = number
  default     = 3
}

variable "events_message_retention_seconds" {
  description = "Retención de mensajes en la cola principal (4 días = 345600)."
  type        = number
  default     = 345600
}

variable "dlq_message_retention_seconds" {
  description = "Retención en la DLQ para inspección (14 días = 1209600, máximo permitido)."
  type        = number
  default     = 1209600
}

variable "long_polling_seconds" {
  description = "Segundos de long polling por recepción (0–20; evita recibir en vacío)."
  type        = number
  default     = 10
}
