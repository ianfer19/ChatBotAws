# Progreso — Paso 6: Infraestructura Terraform base

> **Checklist vivo del Paso 6.** Se actualiza tras cada commit de la fase: `[x]` hecho,
> `[~]` en curso, `[ ]` pendiente. Es la respuesta rápida a «¿qué se hizo y qué falta?»
> sin releer el código. Criterio de cierre del paso:
> [ROADMAP §1 fila 6](../ROADMAP.md). Decisiones de alcance: ADR 0012 (Fase 5).
>
> **Estado global: FASE 2 de 5 completada; siguiente: Fase 3 (aurora + iam).**

## Decisiones cerradas con el usuario (2026-10-09)

- [x] Alcance del cierre: **solo `terraform fmt` + `validate`** (criterio oficial del
      ROADMAP); sin `plan`/`apply` en este paso. El apply manual del bootstrap queda
      documentado en `infra/bootstrap/README.md`.
- [x] Crear `infra/bootstrap/` (backend local, apply único a mano) instanciando
      `modules/state/`, y ampliar CI (`terraform.yml`) y `make tf-validate` para que
      lo validen junto a `envs/*/`.
- [x] ADR 0012 en la Fase 5 con las decisiones estructurales: estructura de envs,
      bootstrap del estado, región `us-east-1`, Lambdas sin VPC por defecto, bucket
      única de archivo con prefijos por tenant.

## Fase 1 — Cimientos: state + bootstrap + backends

- [x] `infra/modules/state/`: S3 de estado (versionado, cifrado SSE-KMS con llave
      `aws/s3`, Block Public Access, `force_destroy=false`, política de solo-TLS)
      + tabla de lock DynamoDB (`LockID`, on-demand).
- [x] `infra/bootstrap/`: backend local propio, `default_tags` por entorno
      (`Environment=shared`), nombre de bucket derivado de la cuenta
      (`chatbot-aws-tfstate-<account_id>`) vía `data.aws_caller_identity`, outputs
      que confirman los nombres y README con el apply único manual.
- [x] `infra/envs/{dev,staging,prod}/backend.tf` (`backend "s3" {}` vacío) +
      `backend.hcl` (bucket, clave por entorno, región, lock, `encrypt=true`);
      init documentado con `-backend-config`, CI lo ignora con `-backend=false`.
- [x] CI (`.github/workflows/terraform.yml`) y `make tf-validate` validan
      `bootstrap/` además de `envs/*/`.
- [x] Docs: `infra/README.md` (uso bootstrap → envs), AGENTS §2 (comentario del
      progress → Paso 6) y §10 fila 6 → **en curso**; este checklist.

## Fase 2 — network + dynamodb + s3  (hecha)

- [x] `network`: VPC + 2 subnets privadas en AZ distintas con una tabla de rutas
      privada; sin NAT/IGW/endpoints por defecto (SECURITY §6: Lambdas fuera de
      VPC); endpoints → `TODO(verify)` cuando un recurso interno lo justifique.
- [x] `dynamodb`: fábrica de tablas (`pk`/`sk`/`ttl` opcionales) on-demand con
      cifrado SSE y llave del entorno — las 5 de `DATA_MODEL` + `pending_actions`
      (ADR 0011, TTL 24 h) + `order_locks`/`appointment_locks` (INTEGRATION §5,
      idempotencia por `correlation_id` → `TODO(verify)` del mecanismo final).
- [x] `s3`: bucket de archivo por entorno con prefijo de cuenta (unicidad
      global), `BucketOwnerEnforced`, Block Public Access, SSE-KMS con llave del
      entorno + bucket key y política solo-TLS; lifecycle → `TODO(verify)`
      (ADR 0007). KMS: módulo nuevo `kms` (una llave por entorno, rotación
      activada) compartida por s3/dynamodb (y Aurora en la Fase 3).
- [x] Cableado en los 3 envs (`versions.tf`, `variables.tf`, `main.tf`,
      `outputs.tf`; CIDRs 10.10/10.20/10.30.0.0/16) + fmt/validate en verde.

## Fase 3 — aurora + iam  (pendiente)

- [ ] `aurora`: PostgreSQL Serverless v2 + pgvector (parameter group), KMS,
      credenciales en Secrets Manager, subnet group/SG en subnets privadas,
      min ACU bajo en dev → `TODO(verify)` de versión de motor.
- [ ] `iam`: factory de roles Lambda least-privilege (rol base + adjuntos por
      función); acciones exactas → `TODO(verify)` (SECURITY §2.3).
- [ ] Claves KMS por entorno si aún no existen (Aurora/S3/DynamoDB) y cableado
      en los 3 envs + fmt/validate en verde.

## Fase 4 — apigw + lambda  (pendiente)

- [ ] `apigw`: HTTP API (v2) con rutas de webhook Meta (`GET/POST /webhook/...`)
      e internas, access logs, integraciones Lambda por ARN variable.
- [ ] `lambda`: factory por mapa de funciones (Python 3.12, handler, env vars,
      timeout/memoria) instanciada con artefactos `artifacts/*.zip` gitignored
      (build posterior) → `TODO(verify)`.
- [ ] Cableado en los 3 envs + fmt/validate en verde.

## Fase 5 — ADR 0012 + docs + cierre  (pendiente)

- [ ] ADR 0012 (estructura de envs, bootstrap, región, sin-VPC por defecto,
      bucket única con prefijos).
- [ ] READMEs de los módulos nuevos y de `envs/{staging,prod}`; CLAUDE.md paso
      activo → 7; AGENTS §1/§10 fila 6 → **hecho**.
- [ ] Batería completa en verde (ruff, format, mypy, pytest, lint-imports,
      terraform fmt, final_review, pyrefly).

## Criterios de hecho del ROADMAP (§1 fila 6)

- [ ] `terraform fmt` + `validate` en verde para dev/staging/prod (CI
      `terraform.yml` ejecuta ambos por directorio).
- [x] Confirmado: los stores de los Pasos 3–5 siguen siendo dobles en memoria
      (este paso crea la infraestructura; los adapters reales llegan en los
      Pasos 6–7 de la ruta, ver ROADMAP §2.4).
- [ ] Batería completa en verde al cierre de la Fase 5.
