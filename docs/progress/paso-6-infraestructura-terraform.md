# Progreso — Paso 6: Infraestructura Terraform base

> **Checklist vivo del Paso 6.** Se actualiza tras cada commit de la fase: `[x]` hecho,
> `[~]` en curso, `[ ]` pendiente. Es la respuesta rápida a «¿qué se hizo y qué falta?»
> sin releer el código. Criterio de cierre del paso:
> [ROADMAP §1 fila 6](../ROADMAP.md). Decisiones de alcance: ADR 0012 (Fase 5).
>
> **Estado global: PASO 6 COMPLETO (5/5 fases); siguiente: Paso 7 (RAG + Aurora/pgvector).**

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

## Fase 3 — aurora + iam  (hecha)

- [x] `aurora`: Serverless v2 (`db.serverless`) con `min_acu`/`max_acu` por
      entorno (dev/staging 0.5–1, prod 1–2 → `TODO(verify pricing)`), parameter
      group con `shared_preload_libraries=vector` (`TODO(verify)`; el
      `CREATE EXTENSION vector` es de la migración del Paso 7), subnets
      privadas, SG que solo admite 5432 desde el CIDR de la VPC, cifrado con
      la llave del entorno, contraseña del master en Secrets Manager
      (`manage_master_user_password`), prod con `deletion_protection` y
      snapshot final.
- [x] `iam`: factory de roles por función (`functions` como set) con confianza
      `lambda.amazonaws.com`, adjunto `AWSLambdaBasicExecutionRole` y mapa
      `inline_policies` para el least-privilege por función →
      `TODO(verify)` de las acciones mínimas al cablear cada adapter.
- [x] Cableado en los 3 envs (aurora + iam con
      `functions = ["conversation_gateway", "supervisor"]`), output
      `aurora_endpoint` y `vpc_cidr` en `network` + fmt/validate en verde.

## Fase 4 — apigw + lambda  (hecha)

- [x] `apigw`: HTTP API (v2) con `GET/POST /webhook` (verificación `hub.challenge`
      y mensajes; la firma la valida la Lambda en el Paso 9), stage
      `$default` con auto-deploy, access logs JSON con `$context` a CloudWatch
      con retención, integraciones `AWS_PROXY` por ruta y `aws_lambda_permission`
      concreto por ruta (no `*`). Rate limiting y rutas internas → Paso 9.
- [x] `lambda`: factory por mapa (Python 3.12, handler, timeout/memoria, env
      `CHATBOT_*`), grupo de logs por función con retención (creado antes que
      la función), `source_code_hash` con `try(filebase64sha256(...))` para
      validar sin zips; `artifacts/` gitignorado salvo su README y
      empaquetado real → `TODO(verify)` (Paso 9).
- [x] Cableado en los 3 envs: funciones `conversation_gateway` (10 s) y
      `supervisor` (60 s, 512 MB) con `CHATBOT_ENVIRONMENT` y
      `CHATBOT_BEDROCK_MODEL_ID`; política inline solo-supervisor para
      `bedrock:InvokeModel*` (ARNs → `TODO(verify)`) y output `api_endpoint`
      + fmt/validate en verde.

## Fase 5 — ADR 0012 + docs + cierre  (hecha)

- [x] ADR 0012 (estructura de envs, bootstrap, región, sin-VPC por defecto,
      bucket única con prefijos) + índice ADR + AGENTS §8 (D9).
- [x] READMEs de los 9 módulos y de `envs/{dev,staging,prod}`; CLAUDE.md paso
      activo → 7; AGENTS §1/§10 fila 6 → **hecho** (y árbol §2 con `kms` y
      `bootstrap/`).
- [x] Batería completa en verde (ruff, format, mypy, pytest, lint-imports,
      terraform fmt, final_review, pyrefly).

## Criterios de hecho del ROADMAP (§1 fila 6)

- [x] `terraform fmt` + `validate` en verde para dev/staging/prod (CI
      `terraform.yml` ejecuta ambos por directorio).
- [x] Confirmado: los stores de los Pasos 3–5 siguen siendo dobles en memoria
      (este paso crea la infraestructura; los adapters reales llegan en los
      Pasos 6–7 de la ruta, ver ROADMAP §2.4).
- [x] Batería completa en verde al cierre de la Fase 5.
