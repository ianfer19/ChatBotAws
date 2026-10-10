# Módulo: kms

Llave simétrica KMS + alias: **una por entorno**, compartida por Aurora,
DynamoDB y S3 (ADR 0012). Rotación anual activada. **Paso 6.**

## Recursos

- `aws_kms_key` (con rotación) + `aws_kms_alias`.

## Variables

| Nombre | Descripción |
| --- | --- |
| `name` | Nombre de la llave/alias (p. ej. `chatbot-aws-dev`). |

## Salidas

`key_arn` (lo consumen `aurora`, `dynamodb` y `s3`) y `key_id`.
