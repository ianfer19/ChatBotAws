# Backend del entorno staging (inyectado en init: terraform init -backend-config=backend.hcl).
# Cada entorno usa una clave distinta dentro del mismo bucket: jamás se comparte
# un state entre entornos.
bucket         = "chatbot-aws-tfstate-029944900353"
key            = "envs/staging/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "chatbot-aws-tfstate-lock"
encrypt        = true
