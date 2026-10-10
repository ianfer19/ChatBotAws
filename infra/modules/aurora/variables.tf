variable "name" {
  description = "Identificador base del clúster (p. ej. `chatbot-aws-dev`); se deriva de él el resto de nombres."
  type        = string
}

variable "vpc_id" {
  description = "VPC donde vive el clúster (subnets privadas del módulo network)."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR de la VPC; único origen permitido al puerto 5432 de la seguridad del clúster."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets privadas del grupo de subnets del clúster (mínimo 2, en AZ distintas)."
  type        = list(string)
}

variable "kms_key_arn" {
  description = "Llave KMS del entorno para cifrar el almacenamiento en reposo."
  type        = string
}

variable "engine_version" {
  description = "Versión mayor de Aurora PostgreSQL (mayor suelta = versión mínima de esa rama)."
  type        = string
  default     = "15"
  # TODO(verify): versión mínima probada y family del parameter group al primer apply.
}

variable "min_acu" {
  description = "ACU mínimas de Serverless v2 (dev usa el mínimo más barato)."
  type        = number
  default     = 0.5
}

variable "max_acu" {
  description = "ACU máximas de Serverless v2 (techo de costo del entorno)."
  type        = number
  default     = 1
}

variable "master_username" {
  description = "Usuario master de la base de datos; la contraseña vive en Secrets Manager (manage_master_user_password)."
  type        = string
  default     = "chatbot_admin"
}

variable "deletion_protection" {
  description = "Protección contra borrado del clúster (siempre `true` en prod)."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Omitir el snapshot final al destruir (dev/staging `true`; prod `false`)."
  type        = bool
  default     = true
}
