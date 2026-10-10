# Módulo: state

Backend remoto de Terraform: bucket S3 para el estado + tabla DynamoDB de lock.
Solo lo instancia `infra/bootstrap/` (apply único a mano; ADR 0012). **Paso 6.**

## Recursos

- `aws_s3_bucket` con versionado, cifrado SSE-KMS (llave gestionada por S3),
  Block Public Access total y política de acceso solo-TLS.
- `aws_dynamodb_table` con clave `LockID` para `terraform lock`.

## Variables

| Nombre | Descripción |
| --- | --- |
| `bucket_name` | Nombre global único (p. ej. `chatbot-aws-tfstate-<account_id>`). |
| `lock_table_name` | Nombre de la tabla de lock (p. ej. `chatbot-aws-tfstate-lock`). |

## Salidas

`bucket_name`, `bucket_arn`, `lock_table_name` — los consumen los `backend.hcl`
de `infra/envs/{dev,staging,prod}/`.
