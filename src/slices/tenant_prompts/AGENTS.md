# Slice: tenant_prompts

> **Fase A de la consola local** (fuera de la ruta de 14 pasos). Estado: **implementado
> con persistencia JSON local** — perfil de comercio, overrides de prompt y restauración
> a la plantilla base. La versión Bedrock Prompt Management + DynamoDB (contenido,
> versiones y pin activo) llega en la **Fase B**.

## Responsabilidad
Selección y carga de la configuración de cada comercio: perfil editable (nombre, tono,
idioma, `allowed_bots`, modelo) y overrides de prompt con fallback a `prompts/base/`.
En la Fase B leerá las versiones publicadas en Bedrock Prompt Management y mantendrá el
pin de la versión activa en DynamoDB, con cacheo, rollback y rollout gradual. No contiene
lógica de negocio ni decide la intención.

## Implementación Fase A
- `domain/entities.py`: `TenantProfile`, `TenantProfileUpdate`, `PromptKind`,
  `default_profile`.
- `domain/ports.py`: `TenantProfileRepositoryPort`.
- `application/service.py`: `TenantConfigService` (perfil, prompts, base y reset).
- `infrastructure/local_json.py`: `LocalJsonTenantRepository` (JSON atómico, lock).
- `prompts/base/*.md`: plantilla base de cada prompt; el override del comercio se
  inyecta en los grafos mediante `system_prompt` (y `tenant_name` en el saludo).

## Entradas y salidas
- Entradas: solicitud de plantilla por clave de operación (p. ej. el especialista de
  ventas) más `tenant_id` y `correlation_id` del contexto, y las versiones publicadas
  en Prompt Management.
- Salidas: el system prompt o fragmento listo para el nodo de LangGraph; logs de carga,
  cache y fallback. Las plantillas fuente residen en `prompts/base/` y
  `prompts/tenants/<tenant_id>/`.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): `PromptRequest` /
  `PromptBundle` (TODO(decision): contrato o `PromptLoaderPort` en `shared/ports/`).
- Consume: `PromptManagementPort` implementado por `adapters/bedrock`, `ClockPort` para
  vigencia y rollout de versiones y el logger estructurado de `shared/logging/`; el
  cacheo por versión vive en el propio infrastructure.

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| `console-data/tenants.json` (local, gitignored) | Perfil y overrides de la consola en la Fase A | Fase A |
| Bedrock Prompt Management | Prompts versionados por operación y tenant | Fase B |
| DynamoDB (pin de versión activa) | Qué versión usa cada tenant | Fase B |
| KMS (cifrado de prompts) | Manejo seguro de las plantillas personalizadas (uso exacto: TODO(verify)) | Fase B |
| CloudWatch Logs | Cargas, caches, rollbacks y fallbacks con `tenant_id` | Fase D |

## Reglas de negocio clave
1. Si falta la personalización del tenant, se usa la plantilla base de `prompts/base/`
   y se registra el fallback.
2. El system prompt de un tenant nunca incluye contenido de otro tenant.
3. Cache por versión; la invalidación al publicar una nueva versión es
   TODO(decision).
4. Rollback mediante pin de versión y rollout gradual; las capacidades exactas de
   Prompt Management para eso son TODO(verify).
5. Sin lógica de negocio ni decisión de intención: eso vive en `domain/` y en
   `supervisor/` (ver `../../../AGENTS.md` §5).
6. El `tenant_id` siempre sale del contexto resuelto en el gateway, jamás del payload
   del LLM.

## Tools expuestas al LLM
— (no expone tools)

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `TenantProfileNotFoundError` | El comercio no existe en la consola | HTTP 404 `tenant_profile_not_found` |
| `PromptOverrideInvalidError` | Prompt vacío, demasiado largo o base ausente | HTTP 400 `prompt_override_invalid` |
| `ValidationError` | JSON local corrupto o perfil fuera de esquema | HTTP 400 sin detalle interno |
| `PromptNotFound` | No existe plantilla para la operación/tenant | Fallback a la base + log warn (Fase B) |
| `PromptVersionCorrupt` | La versión pedida no es válida o está vacía | Fallback a la base + log error (Fase B) |
| `PromptServiceUnavailable` | Prompt Management no responde | Fallback a la base + log error (Fase B) |

## Cómo probarlo
- `tests/unit/test_console_config.py` (Fase A, hecho): siembra, actualización parcial,
  persistencia, override/reset, prompt vacío o largo, tenant desconocido, JSON corrupto
  y aislamiento entre comercios.
- `tests/unit/test_console_runtime.py`: el override llega al `system` del nodo y el
  saludo usa el nombre comercial.
- `tests/unit/test_console_api.py`: contrato HTTP de perfil y prompts.
- `tests/contract/` (Fase B): el system prompt de un tenant nunca incluye prompts de
  otro tenant ni fragmentos de `prompts/tenants/` ajenos.
- `tests/agent_evals/datasets/` (Fase B): operación sin personalización → plantilla base
  y tono del comercio correcto.
