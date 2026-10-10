# Versión mínima compartida por todos los módulos y stacks del repo.
# CI fija 1.9.0 (.github/workflows/terraform.yml) y las estaciones locales
# pueden ser superiores; TODO(verify): fijar la versión exacta al primer apply.
terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 6.0"
    }
  }
}
