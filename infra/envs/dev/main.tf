# Stack de desarrollo: red mínima, KMS y datos operacionales del entorno
# (estado remoto: ver backend.hcl; el resto de módulos llega en las Fases 3–4).

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "chatbot-aws"
      Environment = "dev"
      CostCenter  = "chatbot-aws"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  vpc_cidr = "10.10.0.0/16"

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
  name   = "chatbot-aws-dev"
}

module "network" {
  source      = "../../modules/network"
  name_prefix = "chatbot-aws-dev"
  vpc_cidr    = local.vpc_cidr
}

module "s3" {
  source      = "../../modules/s3"
  name_prefix = "chatbot-aws-dev-archivo"
  kms_key_arn = module.kms.key_arn
}

module "dynamodb" {
  source      = "../../modules/dynamodb"
  environment = "dev"
  kms_key_arn = module.kms.key_arn
  tables      = local.tables
}

module "aurora" {
  source = "../../modules/aurora"
  name   = "chatbot-aws-dev"

  vpc_id      = module.network.vpc_id
  vpc_cidr    = module.network.vpc_cidr
  subnet_ids  = module.network.private_subnet_ids
  kms_key_arn = module.kms.key_arn

  min_acu             = 0.5
  max_acu             = 1
  deletion_protection = false
  skip_final_snapshot = true
}

module "iam" {
  source      = "../../modules/iam"
  environment = "dev"
  functions   = ["conversation_gateway", "supervisor"]
}
