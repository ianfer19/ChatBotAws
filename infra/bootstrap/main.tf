# Estado remoto de Terraform (bootstrap).
#
# Crea el S3 de estado + la tabla de lock DynamoDB que después usan los
# backends de infra/envs/*/. Se aplica UNA SOLA VEZ a mano con credenciales de
# la cuenta (ver README.md); la validación de CI nunca llega aquí: corre con
# `init -backend=false` y sin credenciales.

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "chatbot-aws"
      Environment = "shared"
      CostCenter  = "chatbot-aws"
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Nombre único a nivel global sumando el id de cuenta: el namespace de S3 es
  # compartido entre todas las cuentas del mundo y un sufijo propio evita la
  # colisión con otros proyectos. Debe coincidir con lo escrito en los
  # backend.hcl de envs/ (los outputs lo confirman tras el apply).
  state_bucket_name = "chatbot-aws-tfstate-${data.aws_caller_identity.current.account_id}"
}

module "state" {
  source = "../modules/state"

  bucket_name     = local.state_bucket_name
  lock_table_name = "chatbot-aws-tfstate-lock"
}
