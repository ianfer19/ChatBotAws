# Stack de producción: mismo diseño que dev con su propia VPC, llave y nombres.

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "chatbot-aws"
      Environment = "prod"
      CostCenter  = "chatbot-aws"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  vpc_cidr = "10.30.0.0/16"

  # Una tabla por familia de dato (DATA_MODEL §DynamoDB): PK/SK son los
  # nombres de los atributos; los valores llevan los prefijos `ORG#`, `CONV#`…
  # definidos en DATA_MODEL. `ttl` marca las tablas que expiran.
  tables = {
    chatbot_conversations    = { pk = "PK", sk = "SK", ttl = "ttl" }
    chatbot_customer_context = { pk = "PK", sk = "SK", ttl = "ttl" }
    chatbot_channel_mapping  = { pk = "PK", sk = "SK" }
    chatbot_abuse_limits     = { pk = "PK", sk = "SK", ttl = "ttl" }
    chatbot_tool_audit       = { pk = "PK", sk = "SK", ttl = "ttl" }
    pending_actions          = { pk = "PK", sk = "SK", ttl = "ttl" }
    order_locks              = { pk = "PK", sk = "SK", ttl = "ttl" }
    appointment_locks        = { pk = "PK", sk = "SK", ttl = "ttl" }
  }
}

module "kms" {
  source = "../../modules/kms"
  name   = "chatbot-aws-prod"
}

module "network" {
  source      = "../../modules/network"
  name_prefix = "chatbot-aws-prod"
  vpc_cidr    = local.vpc_cidr
}

module "s3" {
  source      = "../../modules/s3"
  name_prefix = "chatbot-aws-prod-archivo"
  kms_key_arn = module.kms.key_arn
}

module "dynamodb" {
  source      = "../../modules/dynamodb"
  environment = "prod"
  kms_key_arn = module.kms.key_arn
  tables      = local.tables
}
