# Módulo: aurora

Aurora PostgreSQL **Serverless v2** con extensión `pgvector` para el RAG
(Paso 7). **Paso 6.**

## Recursos

- Cluster parameter group con `shared_preload_libraries=vector`, subnet group,
  security group (5432 únicamente desde el CIDR de la VPC), cluster + instancia.
- Contraseña del usuario master en Secrets Manager
  (`manage_master_user_password`); nunca en el repo.

## Variables

| Nombre | Descripción | Default |
| --- | --- | --- |
| `name`, `vpc_id`, `vpc_cidr`, `subnet_ids`, `kms_key_arn` | Identidad, red y cifrado. | — |
| `engine_version` | Versión mayor de Aurora PostgreSQL. | `15` (`TODO(verify)`) |
| `min_acu` / `max_acu` | Techo de ACU (0.5–1 en dev/staging, 1–2 en prod). | `0.5` / `1` |
| `master_username` | Usuario master (contraseña en Secrets Manager). | `chatbot_admin` |
| `deletion_protection` / `skip_final_snapshot` | Protección en prod (`true`/`false`). | `false` / `true` |

## Salidas

`cluster_endpoint` (endpoint de escritura para RAG), `cluster_id`,
`master_secret_arn`.

## Migración inicial (Paso 7)

El esquema **no** lo aplica Terraform: se ejecuta a mano, una vez, contra el
entorno correspondiente (idempotente, se puede re-ejecutar):

```bash
psql "$CONNINFO" -f infra/modules/aurora/migrations/001_knowledge.sql
```

- `$CONNINFO` usa el endpoint del stack (`terraform output aurora_endpoint`), el
  usuario `chatbot_admin` y la contraseña del secreto `master_secret_arn`
  (`aws secretsmanager get-secret-value ... --query SecretString`).
- El cliente **tiene que correr desde dentro de la VPC** (el security group solo
  acepta 5432 desde su propio CIDR): túnel, bastión o runner dentro de la red.
  `TODO(verify)`: mecanismo definitivo de aplicación de migraciones (¿Aurora
  Data API?, ¿migrador empaquetado en la Lambda?).
- El adapter `adapters/aurora` asume este esquema (`knowledge_chunks` con
  `vector(1536)` + tabla `documents`).
