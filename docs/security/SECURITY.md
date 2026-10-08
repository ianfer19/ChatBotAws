# Seguridad

Documento de la Fase 1 (esqueleto). Principios, superficie de entrada y salida, controles
de IAM/KMS/secrets y el checklist que todo slice debe pasar antes de publicarse. Las
amenazas concretas y sus capas de mitigación viven en [THREAT_MODEL.md](./THREAT_MODEL.md);
la retención de datos, en [DATA_RETENTION.md](./DATA_RETENTION.md). Todo dato de AWS no
confirmado aparece como `TODO(verify)`.

Ver también: [../architecture/OVERVIEW.md](../architecture/OVERVIEW.md),
[../architecture/MULTI_TENANCY.md](../architecture/MULTI_TENANCY.md),
[../architecture/HEXAGONAL_AND_SLICING.md](../architecture/HEXAGONAL_AND_SLICING.md),
[../adr/README.md](../adr/README.md), [`../../AGENTS.md`](../../AGENTS.md).

## 1. Principios

| # | Principio | Qué implica en este repo | Cómo se verifica |
|---|---|---|---|
| P1 | Defensa en profundidad | Ninguna capa es la única barrera. La misma regla se repite en prompt, Guardrails, `domain/`, AgentCore Policy y tests: si una capa falla, otra contiene. | Tests por capa (`tests/unit`, `tests/contract`, `tests/integration`) y evals (`tests/agent_evals`) |
| P2 | Least privilege en IAM | Un rol por función, sin políticas amplias ni `*`; cada Lambda solo toca los recursos de su slice y su entorno. | Revisión de `infra/modules/iam` en cada PR; diff de permisos obligatorio |
| P3 | Zero secrets en el repo | Sin credenciales, tokens, `.env` reales ni dumps en código, prompts, docs ni logs. Los secretos viven fuera (sección 5). | Escaneo de secretos en pre-commit y CI (sección 7) |
| P4 | Mínimo privilegio para el LLM | El modelo solo ve las tools que el tenant tiene derecho a usar, con schema, validación, autorización por tenant, timeout, idempotencia y logs. Nunca toca la BD directamente ni elige el `tenant_id`. | Schemas de tools sin `tenant_id`; validación Pydantic de su salida |
| P5 | Denegación por defecto | Sin permiso explícito no hay acción: AgentCore Policy con Cedar/Dogwood en default-deny y forbid-wins; sin mapeo de canal, rechazo en el gateway. | Tests de negación; ninguna acción "por defecto" |
| P6 | Todo entra validado, todo sale auditado | Entrada validada por contratos (`src/shared/contracts`); salida con `tenant_id` y `correlation_id` obligatorios en cada log. | Test estructural del logger: un log sin `tenant_id` es bug |

## 2. Superficie de entrada y salida

### 2.1 Webhook Meta (API Gateway → `conversation_gateway`)

Es el único punto HTTP público del sistema. Controles obligatorios:

| Control | Qué se hace | Si falla |
|---|---|---|
| Verificación `hub.challenge` | Responder al GET de verificación con el `verify_token` configurado; el token vive en Secrets Manager, nunca en el repo. | No se responde o se responde 403; sin handshake no hay webhook. |
| Firma `X-Hub-Signature-256` | Recalcular el HMAC-SHA256 del cuerpo con el app secret y compararlo en tiempo constante con la cabecera. Sin cabecera o con distinto → rechazo. | 403 + log `action=deny, reason=bad_signature`; el cuerpo ni se parsea. |
| Rate limiting | Limitar por remitente y por tenant en dos capas: throttling en API Gateway y contadores en `abuse_protection`. Umbrales en [THREAT_MODEL.md](./THREAT_MODEL.md) sección 7. | 429 o encolado descartado con log; nunca un loop de reintentos. |
| Origen | Restringir el tráfico a las IPs/publicación de Meta del webhook → `TODO(verify)` (lista y política de publicación de Meta). | Si Meta no publica lista estable, se valida solo por firma y se documenta la excepción. |
| Contrato del payload | Validar tamaño, campos y tipos con Pydantic antes de encolar; idempotencia por id de mensaje de Meta para reintentos. | Descarte con `action=deny, reason=invalid_payload` + `correlation_id`. |
| Resolución del tenant | `tenant_id` sale del mapeo de canal replicado, **nunca** del payload. Sin mapeo → rechazo. | `reason=unmapped_channel`; jamás se procesa "sin tenant". |

### 2.2 Entradas internas

- **SQS**: cada mensaje se valida de nuevo contra su modelo de `src/shared/contracts` al
  consumirlo; `tenant_id` y `correlation_id` son campos requeridos, no opcionales.
- **Media entrante (imágenes/audios)**: validar tipo, tamaño y extensión antes de escribir en
  S3 bajo el prefijo del tenant; `media_handling` no ejecuta ni renderiza contenido del
  cliente. Análisis de malware → `TODO(verify)` (necesidad y herramienta).
- **Consultas salientes al legacy**: solo desde el adapter
  `src/adapters/legacy_backend` vía AgentCore Gateway, nunca desde `domain/`.

### 2.3 Salida: tools hacia el backend legacy

El LLM no habla con la BD ni con el legacy: invoca tools publicadas tras AgentCore Gateway.

| Control | Implementación | Capa |
|---|---|---|
| Schema | Cada tool se define con schema Pydantic (`src/shared/contracts`); lo que el modelo devuelve fuera del schema es error, no se ejecuta. | contrato |
| Autorización por tenant | El `tenant_id` lo inyecta el adaptador desde el contexto, después de validar la respuesta del modelo; un `tenant_id` ajeno se descarta y se audita. | adaptador + AgentCore Policy (default-deny por tenant) |
| Timeout | Timeout por llamada y presupuesto de reintentos acotados; nunca reintentos infinitos contra el legacy. | adaptador HTTP |
| Idempotencia | Clave de idempotencia por invocación para que un reintento no duplique una cita o un pedido. | application + legacy |
| Logs de auditoría | Cada invocación registra `correlation_id`, `tenant_id`, tool, resultado y latencia; sin parámetros sensibles ni PII innecesaria. | `src/shared/logging` |
| Disponibilidad de tools | Solo se construyen las tools del tenant (`allowed_bots`); el resto no llega al modelo. | `supervisor` + `tenant_prompts` |

## 3. IAM por función

Los nombres exactos de acciones, ARNs y condiciones se definen en `infra/modules/iam`
(Paso 6) → `TODO(verify)` (acciones IAM mínimas por rol). La regla es la tabla siguiente;
lo que no aparece, no se concede.

| Rol / función | Paso · slice | Permisos mínimos (conceptuales) | Prohibido |
|---|---|---|---|
| `lambda_webhook` | 9 · `conversation_gateway` | Enviar a SQS, leer el mapeo de canal, leer `verify_token`/app secret, escribir logs | Leer conversaciones ajenas, invocar modelos |
| `lambda_supervisor` | 4 · `supervisor` | Invocar los modelos del `LLMPort`, leer/escribir checkpointer en DynamoDB, escribir logs/métricas | Acceder a Aurora o S3, gestionar claves |
| `lambda_customer_context` | 4 · `customer_context` | Leer contexto de cliente en DynamoDB, escribir logs | Escribir en tablas de configuración |
| `lambda_tenant_prompts` | fuera de ruta · `tenant_prompts` | Resolver la versión de prompt del tenant, escribir logs | Publicar prompts de otros tenants |
| `lambda_knowledge_rag` | 7 · `knowledge_rag` | Ejecutar queries con filtro `tenant_id` sobre Aurora usando el secreto de BD, escribir logs | Escrituras fuera del esquema de conocimiento, acceso a DynamoDB operacional |
| `lambda_orders` / `lambda_appointments` | 5 · `orders`, `appointments` | Invocar tools publicadas en AgentCore Gateway, leer credenciales del legacy, escribir logs | Invocar tools de otro tenant, modificar recursos del legacy fuera de las tools |
| `lambda_sentiment_handoff` | fuera de ruta · `sentiment_handoff` | Analizar el mensaje actual con Comprehend, marcar handoff en DynamoDB, escribir logs | Leer historial completo de otros tenants |
| `lambda_abuse_protection` | fuera de ruta · `abuse_protection` | Leer/escribir contadores y bloqueos en DynamoDB (con TTL), escribir logs | Bloquear sin dejar motivo en auditoría |
| `lambda_media_handling` | fuera de ruta · `media_handling` | Leer/escribir objetos bajo `/<tenant_id>/` en S3, escribir logs | Listar o leer prefijos de otros tenants |
| `lambda_retention_archiving` | fuera de ruta · `retention_archiving` | Consumir DynamoDB Streams, mover/borrar objetos de S3 por prefijo, escribir logs | Borrar sin registro de auditoría |
| `agentcore_gateway_role` | 11 · tools al legacy | Invocar las APIs publicadas, leer credenciales del legacy | Cualquier acceso directo a Aurora/DynamoDB nuestros |
| `role_terraform_ci` | 6 · CI/CD | Desplegar por entorno, leer/escribir el estado S3 + lock | Acceder a datos de clientes o a secretos de producción en PRs |

Reglas transversales: sin `*`; sin permisos entre entornos (un rol por entorno); las
Lambdas jamás leen ni escriben el estado de Terraform; todo cambio de permisos se revisa
como cambio de seguridad, no como refactor.

## 4. KMS

| Recurso | Cifrado | Notas |
|---|---|---|
| Aurora PostgreSQL | En reposo con KMS | Clave por entorno; el secreto de BD va en Secrets Manager. Rotación → `TODO(verify)` |
| DynamoDB | En reposo con KMS | Tablas operacionales (checkpointer, contadores, auditoría); clave por entorno |
| S3 | En reposo con KMS | Buckets de archivo de conversaciones y de media; políticas de bucket restringen el prefijo por tenant |
| Prompts por tenant | Cifrado en reposo del servicio de prompts | Cómo asociar la clave en Bedrock Prompt Management → `TODO(verify)` |
| Logs y colas | Verificar cifrado y quién puede leerlos | Defaults y necesidad de clave propia → `TODO(verify)` |

Reglas: una CMK por entorno (`dev`/`staging`/`prod`), sin claves compartidas entre
entornos; la política de la clave lista los roles de la sección 3, nada más; uso de la
clave auditado → `TODO(verify)` (CloudTrail de KMS).

## 5. Secrets Manager vs. SSM Parameter Store

| Tipo de dato | Servicio | Ejemplos | Rotación |
|---|---|---|---|
| Secreto real, con rotación o por tenant | Secrets Manager | `access_token` de canal por tenant, app secret de Meta, `verify_token`, credenciales del legacy | Rotación gestionada donde exista → `TODO(verify)` (mecanismo y coste: `TODO(verify pricing)`) |
| Configuración no sensible | SSM Parameter Store (estándar) | ARNs, flags de habilitación, umbrales de abuso, identificadores de modelo | Cambio por despliegue, versionado |
| Secreto compartido con el legacy | Secrets Manager | Token de servicio con el que el gateway habla al legacy | Coordinado con `sahagunonline/back` → `TODO(verify)` |

Reglas: nada secreto en el repo, en `prompts/`, en variables de entorno hardcodeadas ni en
logs; la Lambda resuelve el secreto en runtime desde su rol; si un secreto se cuela en un
commit, se rota en el servicio, se revoca en el origen (p. ej. Meta) y se revisan los logs
desde el `correlation_id` afectado.

## 6. VPC y endpoints

- **Por defecto, las Lambdas corren sin VPC**: menos superficie, cero coste de red extra.
  Se adjuntan a la VPC solo si el recurso lo exige (p. ej. Aurora en subnets privadas).
- **Aurora queda en subnets privadas**, accesible solo desde las Lambdas autorizadas, con
  security groups de origen ajustado al grupo de Lambdas correspondiente.
- **VPC endpoints solo donde se justifiquen**: si un componente dentro de la VPC necesita
  hablar con un servicio AWS sin salir por internet, o si un control de tráfico lo exige.
  Cada endpoint se justifica en su módulo con su coste y soporte → `TODO(verify)`.
- **Pública solo la entrada del webhook** (API Gateway). No se exponen otros servicios.
- El tráfico saliente al legacy y a Meta sale por la ruta estándar → `TODO(verify)`
  (si en algún momento se requiere NAT o salida restringida).

## 7. Entrada de código y dependencias

### 7.1 Pre-commit y detección de secretos

- `pre-commit` local con formateo, lint, chequeo de tipos rápido y detección de secretos
  antes del commit; el mismo bloque se repite en CI para quien lo salte.
- Herramienta de detección de secretos: **gitleaks** o **GitGuardian** → `TODO(verify)`.
- Prohibido commitear: credenciales, `.env` reales, dumps de BD, tokens de Meta, claves KMS,
  transcripts de conversaciones de clientes.

### 7.2 Dependencias

- Versiones fijadas (pinning) y dependencias mínimas: `domain/` solo `stdlib`, `pydantic` y
  `shared/` (ver [../architecture/HEXAGONAL_AND_SLICING.md](../architecture/HEXAGONAL_AND_SLICING.md)).
- Auditoría de vulnerabilidades con `pip audit` (o equivalente) en CI → `TODO(verify)`
  (herramienta definitiva, umbral de severidad que rompe el build y frecuencia del análisis).
- Actualizaciones por PR revisado; cambios mayores solo con tests en verde.

## 8. CI

| Check | Qué comprueba | Bloquea el merge |
|---|---|---|
| Lint | Estilo y errores estáticos básicos en todo `src/` | Sí |
| Tipos | Chequeo de tipos en `src/shared`, `src/adapters` y `domain/` de cada slice | Sí |
| Tests | `tests/unit`, `tests/contract`, `tests/integration` | Sí |
| import-linter | Las cuatro reglas de dependencia (handler → application → domain; infrastructure → domain; dominio aislado; slices aislados) | Sí |
| Escaneo de secretos | Ningún secreto en el diff ni en el historial nuevo (sección 7.1) | Sí |
| Auditoría de dependencias | CVEs por encima del umbral (sección 7.2) | Sí (umbral → `TODO(verify)`) |

El detalle de los flujos vive en `.github/workflows/` (`ci.yml` y `terraform.yml`,
creados en Fase 1); los checks de secretos y de auditoría de dependencias de esta tabla
**aún no están** en ellos → `TODO(verify)` (añadir en su paso y nombres exactos de jobs).

## 9. Checklist antes de publicar un slice

- [ ] Ningún secreto, token ni valor sensible en el código, en `prompts/` ni en los docs.
- [ ] Rol IAM del slice con permisos mínimos; diff de permisos revisado en el PR.
- [ ] Entrada validada con contrato (`src/shared/contracts`); rechazo con log `action=deny`.
- [ ] `tenant_id` resuelto del contexto, nunca del payload ni de argumentos de una tool.
- [ ] Tools con schema, validación, timeout, idempotencia y logs con `correlation_id` + `tenant_id`.
- [ ] Reglas de negocio en `domain/`, no en prompts; ninguna verdad de precios/stock/horas en el modelo.
- [ ] Cifrado y secretos donde corresponda (secciones 4 y 5).
- [ ] Tests nuevos: unit (dominio), contract (contratos), integration (adaptadores).
- [ ] import-linter, lint, tipos y escaneo de secretos en verde.
- [ ] Amenazas nuevas añadidas a [THREAT_MODEL.md](./THREAT_MODEL.md) con su capa de mitigación.
- [ ] Ningún `TODO(verify)` nuevo sin propietario ni fecha de revisión.
- [ ] Si el slice cambia comportamiento operativo, existe (o se crea) su runbook en
      [`../runbooks/README.md`](../runbooks/README.md).
- [ ] Revisión humana de código obligatoria; no se publica sin aprobación.

## 10. Referencias

- [THREAT_MODEL.md](./THREAT_MODEL.md) — amenazas, capas y umbrales de abuso.
- [DATA_RETENTION.md](./DATA_RETENTION.md) — retención y borrado de datos.
- [../architecture/MULTI_TENANCY.md](../architecture/MULTI_TENANCY.md) — aislamiento por tenant.
- [../adr/README.md](../adr/README.md) — decisiones registradas y su estado.
- [`../../AGENTS.md`](../../AGENTS.md) — convenciones del repo.
