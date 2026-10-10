variable "name_prefix" {
  description = "Prefijo para el `Name` de VPC y subnets (p. ej. `chatbot-aws-dev`)."
  type        = string
}

variable "vpc_cidr" {
  description = "Bloque CIDR de la VPC (p. ej. `10.10.0.0/16`); las subnets salen de `cidrsubnet`."
  type        = string
}
