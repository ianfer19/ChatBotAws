variable "environment" {
  description = "Entorno que posee los roles; aparece en el nombre de cada uno."
  type        = string
}

variable "functions" {
  description = "Nombres lógicos de las Lambdas del entorno; uno crea un rol con least-privilege (SECURITY §2)."
  type        = set(string)
  nullable    = false
}

variable "inline_policies" {
  description = <<-EOT
    Mapa función → política JSON propia (acciones concretas que esa función
    necesita, p. ej. `bedrock:InvokeModel` para el supervisor). Las claves
    deben existir en `functions`. Vacío = solo logs de CloudWatch.
  EOT
  type        = map(string)
  default     = {}
  nullable    = false
}
