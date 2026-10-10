variable "environment" {
  description = "Entorno que posee las tablas; se añade como sufijo del nombre (`<tabla>_<entorno>`)."
  type        = string
}

variable "tables" {
  description = <<-EOT
    Mapa de tablas a crear, indexado por el nombre lógico de DATA_MODEL.
    `pk`/`sk` son los NOMBRES de los atributos clave (los valores llevan los
    prefijos `ORG#`, `CONV#`, etc. definidos en DATA_MODEL §DynamoDB);
    `ttl` es el atributo TTL numérico (`null` = la tabla no expira).
  EOT
  type = map(object({
    pk  = string
    sk  = optional(string)
    ttl = optional(string)
  }))
  nullable = false
}

variable "kms_key_arn" {
  description = "ARN de la llave KMS del entorno; `null` usa el cifrado gestionado por AWS."
  type        = string
  default     = null
}
