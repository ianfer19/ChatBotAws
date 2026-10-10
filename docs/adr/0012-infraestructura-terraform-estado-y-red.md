# 0012. Infraestructura Terraform: estado remoto, tres entornos y red mínima

- **Estado:** Aceptado
- **Fecha:** 2026-10-09
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El Paso 6 de la [ruta](../ROADMAP.md) crea la base sobre la que se desplegará el
sistema (Pasos 7–13): estado remoto, red, DynamoDB, S3, Aurora, IAM, API Gateway y
Lambdas para `dev`/`staging`/`prod`. El criterio de cierre es solo `terraform fmt` +
`validate` en verde —es decir, la infraestructura tiene que **diseñarse y validarse
sin credenciales ni recursos reales**—, pero el diseño condiciona todos los pasos
posteriores. Fuerzas en conflicto:

1. **El estado de Terraform no puede guardarse a sí mismo** (chicken-egg): hace falta
   un primer estado local y un mecanismo para migrarlo.
2. [SECURITY §6](../security/SECURITY.md) exige que **las Lambdas corran sin VPC por
   defecto** y que solo lo que lo necesite (Aurora) viva en red privada; cada VPC
   endpoint o NAT es costo fijo que hay que justificar.
3. [DATA_MODEL](../architecture/DATA_MODEL.md) y
   [ADR 0002](0002-reparto-de-datos-aurora-dynamodb-s3.md) fijan qué tablas y buckets
   existen, pero **no** los nombres de atributo de las claves (`ORG#…` es el *valor*,
   no el atributo) ni cómo se reparten por entorno en una misma cuenta.
4. Un solo bucket S3 por cuenta (namespace global) y una sola región de trabajo
   (Bedrock `us-east-1` y los webhooks de Meta).

## Decisión

**Módulos reutilizables + un stack por entorno, estado remoto con bootstrap
separado y la red lo más mínima posible.** Implica:

1. **Estructura**: `infra/modules/<módulo>` (reutilizable, sin backend) e
   `infra/envs/<env>/{main,versions,variables,outputs,backend}.tf` (root module con
   provider y `default_tags`). Un **state por entorno**: clave
   `envs/<env>/terraform.tfstate`; jamás se comparte un state.
2. **Bootstrap separado** en `infra/bootstrap/`: crea el bucket de estado + la tabla
   de lock con **backend local** y se aplica **una única vez a mano**
   (`bootstrap/README.md`). CI solo hace `init -backend=false` + `validate`.
3. **Backend declarativo**: `backend "s3" {}` vacío en cada entorno + `backend.hcl`
   commiteado (bucket, clave, región, lock, `encrypt`); init con
   `terraform init -backend-config=backend.hcl`. La CI nunca resuelve el backend.
4. **Una sola región**: `us-east-1` (Bedrock y Meta la usan ya); multi-región →
   `TODO(decision)`.
5. **Red mínima** (`network`): VPC + 2 subnets privadas + ruta privada; **sin NAT,
   sin IGW, sin endpoints** por defecto — las Lambdas no viven en la VPC y Aurora no
   necesita salida a internet. VPC endpoints → `TODO(verify)` cuando un recurso
   interno lo justifique.
6. **Cifrado**: una llave KMS **por entorno** (módulo `kms`, rotación activada)
   compartida por Aurora, DynamoDB y S3; el bucket de estado usa la llave gestionada
   por S3 (`aws/kms` sin llave propia). Nada de secretos en el repo: la contraseña
   del master de Aurora vive en Secrets Manager (`manage_master_user_password`).
7. **Naming y tags**: recursos `chatbot-aws-<entorno>-*` y `default_tags`
   (`Project`, `Environment`, `CostCenter`, `ManagedBy`) en todos los roots.
8. **DynamoDB**: una tabla por familia de dato de DATA_MODEL **con sufijo de
   entorno** (`chatbot_conversations_dev`, …) más `pending_actions` (ADR 0011) y
   `order_locks`/`appointment_locks` (idempotencia, INTEGRATION §5 →
   `TODO(verify)` del mecanismo final). **Los atributos clave se fijan aquí como
   `PK`/`SK`** (DATA_MODEL define solo los valores `ORG#…`); TTL en atributo `ttl`;
   on-demand sin GSI (el adapter del Paso 8 → `TODO(verify)` si necesita otra ruta).
9. **S3 de archivo**: un bucket por entorno con prefijos por tenant
   (`<tenant_id>/conversations|media`, DATA_MODEL), Block Public Access total y
   `BucketOwnerEnforced` (sin ACLs); lifecycle → `TODO(verify)` (ADR 0007).
10. **Lambdas y API**: dos funciones de entrada hoy (`conversation_gateway`,
    `supervisor`), rol IAM propio por función con política inline mínima
    (`bedrock:InvokeModel*` solo para el supervisor), zips fuera del repo
    (`artifacts/*.zip` gitignorado; `source_code_hash` con `try()` para validar sin
    artefacto) y API Gateway HTTP con `GET/POST /webhook` y permiso por ruta.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
|---|---|---|---|
| Un bucket de estado **por entorno** | Aislamiento físico total | Más recursos y nombres que gestionar; el lock por state ya aísla los states | El aislamiento real está en claves y tablas de lock distintas; un bucket basta y cuesta lo mismo |
| `apply` del bootstrap desde CI/CD | Cero pasos manuales | Exige credenciales de cuenta en CI desde el primer día (rol `role_terraform_ci` aún no existe) | Criterio del paso = `fmt`+`validate` sin credenciales; el rol de CI queda `TODO(verify)` |
| VPC con NAT para las Lambdas | Todo sale por IP fija | Costo fijo de NAT + bastión de tráfico que SECURITY §6 evita por defecto | Se descarta: Lambdas fuera de VPC; solo Aurora entra a la red privada |
| Single-table: una tabla DynamoDB por entorno (como el legacy) | Menos tablas que operar | DATA_MODEL prioriza legibilidad y aislamiento por familia en la Fase 1; migrar después es mecánico | Se descarta por ahora; DATA_MODEL ya deja abierta la consolidación |
| Atributos de clave `pk`/`sk` minúsculos | Estilo moderno | DATA_MODEL no fija el nombre; hay que elegir uno y mantenerlo | Se fija `PK`/`SK` (estilo single-table del legacy) para no contradecir los docs |

## Consecuencias

### Positivas

- CI valida **toda** la infraestructura (bootstrap + 3 entornos) sin credenciales ni
  backend desplegado; `plan/apply` son procedimientos manuales documentados.
- Estado protegido: versionado, cifrado, Block Public Access, política solo-TLS y
  lock DynamoDB; un state por entorno con claves y lock propios.
- Costos de dev contenidos: Aurora min 0.5 ACU, DynamoDB on-demand, sin NAT ni
  endpoints, logs con retención, una KMS por entorno.
- Nombres, tags y esquema de claves estables y documentados: los adapters de los
  Pasos 7–8 pueden escribirse contra ellos sin adivinar.

### Negativas / riesgos

- `backend.hcl` lleva el id de cuenta escrito: cambiar de cuenta obliga a
  actualizar los tres archivos (los outputs del bootstrap lo confirman).
- El primer `plan/apply` real puede revelar parámetros mal interpretados
  (`TODO(verify)` abiertos: versión/motor de Aurora, `shared_preload_libraries` de
  pgvector, ARNs de Bedrock, acciones IAM mínimas, empaquetado de Lambda).
- Sin detección de drift en CI todavía (el rol de CI/CD está pendiente).

## Relacionados

- [ROADMAP §1 fila 6](../ROADMAP.md) · [infra/README.md](../../infra/README.md)
- [SECURITY §2–§6](../security/SECURITY.md) · [DATA_MODEL](../architecture/DATA_MODEL.md)
- [ADR 0002](0002-reparto-de-datos-aurora-dynamodb-s3.md) (reparto de datos) ·
  [ADR 0007](0007-retencion-de-conversaciones-y-media.md) (lifecycle de S3) ·
  [ADR 0011](0011-confirmacion-por-politica-con-drafts.md) (`pending_actions`)
