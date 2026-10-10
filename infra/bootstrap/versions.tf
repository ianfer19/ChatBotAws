# Versión compartida (ver infra/modules/state/versions.tf).
terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 6.0"
    }
  }

  # Backend local explícito: este estado vive en este directorio (gitignorado)
  # porque es justamente el estado que este módulo se encarga de crear fuera de
  # aquí. Un backend no puede guardarse a sí mismo («chicken-egg»).
  backend "local" {
    path = "terraform.tfstate"
  }
}
