# Infraestructura (Terraform)

Módulos reutilizables en `modules/` y stacks por entorno en `envs/{dev,staging,prod}/`.
Estado remoto en S3 con lock en DynamoDB (módulo `state/`).

## Convenciones

- **Módulos pequeños y tipados**: cada variable con `type` y `description`; salidas
  (`outputs`) mínimas y estables.
- **Un state por entorno** (`envs/<env>/`), jamás states compartidos.
- **Tags obligatorias** en todos los recursos: `Project = "chatbot-aws"`,
  `Environment`, `CostCenter`, `ManagedBy = "terraform"` y, cuando aplica, `Tenant`.
- **KMS** en Aurora, DynamoDB, S3 y prompts; sin buckets públicos.
- **IAM least-privilege por función**: un rol por Lambda, solo las acciones que usa.
- **Secretos** en Secrets Manager (o SSM con encriptación); nunca en `tfvars` del repo.
- **VPC endpoints** solo donde el tráfico lo justifique (costo fijo vs. NAT) —
  `modules/network/`.
- **`terraform fmt` + `validate`** en CI (`.github/workflows/terraform.yml`).

## Módulos

| Módulo | Qué crea | Costo estimado (orden de magnitud) | Fase |
|---|---|---|---|
| `state/` | S3 de estado + lock DynamoDB | < 1 USD/mes (`TODO(verify pricing)`) | 3 |
| `network/` | VPC mínima + endpoints | endpoints desde ~USD 0.01/h c/u (`TODO(verify pricing)`) | 3 |
| `aurora/` | Aurora PostgreSQL Serverless v2 + pgvector, KMS | desde ~USD 20–40/mes con min ACU bajo + storage (`TODO(verify pricing)`) | 3 |
| `dynamodb/` | Tablas operacionales con TTL (on-demand) | < 5 USD/mes a volumen inicial (`TODO(verify pricing)`) | 3 |
| `s3/` | Buckets de archivo/media con lifecycle y KMS | ~USD 0.023/GB-mes (`TODO(verify pricing)`) | 3 |
| `lambda/` | Paquetes e IAM por función (Python 3.12) | ~USD 0.20/millón de invocaciones + compute (`TODO(verify pricing)`) | 3 |
| `apigw/` | API Gateway HTTP (webhook Meta, internos) | ~USD 1/millón de llamadas (`TODO(verify pricing)`) | 3 |
| `bedrock/` | Guardrails y acceso a modelos | por token; depende del modelo (`TODO(verify pricing)`) | 5 |
| `agentcore/` | Runtime, Memory, Gateway, Identity, Policy | pay-as-you-go por uso/sesión (`TODO(verify pricing)`) | 8 |
| `iam/` | Roles/políticas compartidos least-privilege | — | 3 |
| `observability/` | Logs JSON, métricas, alarmas, dashboard | por ingesta de logs (`TODO(verify pricing)`) | 9 |

> Los precios son estimaciones de referencia; verificar en la calculadora de AWS antes de
> decidir (marcados `TODO(verify pricing)`). El entorno **dev** usa min ACU bajo en Aurora
> y apaga recursos caros cuando no se usan.

## Uso

```bash
cd infra/envs/dev
terraform init
terraform plan
terraform apply
```

```bash
# Validación local (igual que en CI)
terraform fmt -check -recursive infra
make tf-validate
```

`make tf-validate` hace `init -backend=false` + `validate` por entorno; `plan/apply`
requieren credenciales AWS y el backend `state/` ya desplegado (Fase 3).
