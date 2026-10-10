# Módulo: s3

Bucket de archivo por entorno para conversaciones y media, con prefijos por
tenant (`<tenant_id>/conversations|media`; DATA_MODEL). **Paso 6.**

## Recursos

- `aws_s3_bucket` + ownership `BucketOwnerEnforced` (sin ACLs), Block Public
  Access total, cifrado SSE con la llave del entorno y política solo-TLS.

## Variables

| Nombre | Descripción |
| --- | --- |
| `name_prefix` | Prefijo único por cuenta (p. ej. `chatbot-aws-dev-<account_id>`). |
| `kms_key_arn` | Llave del entorno para cifrado en reposo. |

## Salidas

`bucket_name`, `bucket_arn`.

## Notas

Lifecycle de retención → `TODO(verify)` con ADR 0007 (fuera de la ruta actual).
