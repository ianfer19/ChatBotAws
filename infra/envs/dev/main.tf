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
    chatbot_checkpoints      = { pk = "PK", sk = "SK", ttl = "ttl" }
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

  # Least-privilege por función: solo el supervisor habla con Bedrock.
  # TODO(verify): ARNs exactos (foundation-model vs inference-profile) al
  # cablear el adapter real (Pasos 7–10).
  inline_policies = {
    supervisor = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid    = "BedrockConverse"
          Effect = "Allow"
          Action = [
            "bedrock:InvokeModel",
            "bedrock:InvokeModelWithResponseStream",
          ]
          Resource = [
            "arn:aws:bedrock:${var.aws_region}::foundation-model/*",
            "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/*",
          ]
        },
        {
          Sid    = "CheckpointsDeConversacion"
          Effect = "Allow"
          Action = [
            # TODO(verify): acciones mínimas del checkpointer (Paso 8); revisar
            # si `dynamodb:PartiQL*` o condicionales reducen más el permiso.
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:DeleteItem",
          ]
          Resource = [
            "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${module.dynamodb.table_names["chatbot_checkpoints"]}",
          ]
        },
      ]
    })
  }
}

data "aws_caller_identity" "current" {}

# Lambda + API HTTP: los dos puntos de entrada del entorno (ADR 0004: el grafo
# corre en Lambda en dev; el webhook llega por API Gateway).
locals {
  # TODO(decision): modelo por entorno (hoy el mismo que el del smoke; costos → Paso 14).
  model_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

  lambda_functions = {
    conversation_gateway = {
      handler  = "handler.main"
      zip_path = "../../../artifacts/conversation_gateway.zip"
      timeout  = 10
      env = {
        CHATBOT_ENVIRONMENT      = "dev"
        CHATBOT_BEDROCK_MODEL_ID = local.model_id
      }
    }
    supervisor = {
      handler     = "handler.main"
      zip_path    = "../../../artifacts/supervisor.zip"
      timeout     = 60
      memory_size = 512
      env = {
        CHATBOT_ENVIRONMENT       = "dev"
        CHATBOT_BEDROCK_MODEL_ID  = local.model_id
        CHATBOT_CHECKPOINTS_TABLE = module.dynamodb.table_names["chatbot_checkpoints"]
      }
    }
  }
}

module "lambda" {
  source      = "../../modules/lambda"
  environment = "dev"
  functions   = local.lambda_functions
  role_arns   = module.iam.role_arns
}

module "apigw" {
  source      = "../../modules/apigw"
  name        = "chatbot-aws-dev"
  environment = "dev"
  functions   = module.lambda.invoke_arns

  routes = {
    webhook_get  = { method = "GET", path = "/webhook", function = "conversation_gateway" }
    webhook_post = { method = "POST", path = "/webhook", function = "conversation_gateway" }
  }
}
