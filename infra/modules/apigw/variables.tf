variable "name" {
  description = "Nombre de la API HTTP (p. ej. `chatbot-aws-dev`)."
  type        = string
}

variable "environment" {
  description = "Entorno; forma parte del nombre real de las Lambdas para los permisos de invocación."
  type        = string
}

variable "functions" {
  description = "Mapa nombre lógico → invoke_arn de su Lambda (salida del módulo lambda)."
  type        = map(string)
  nullable    = false
}

variable "routes" {
  description = "Mapa de rutas: método, path y función lógica destino (la clave identifica la ruta en logs)."
  type = map(object({
    method   = string
    path     = string
    function = string
  }))
  nullable = false
}

variable "log_retention_days" {
  description = "Días de retención de los access logs de la API en CloudWatch."
  type        = number
  default     = 14
}
