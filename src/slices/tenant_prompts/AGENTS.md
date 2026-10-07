# Slice: tenant_prompts

> Fase de implementación: **Fase 5**. Estado: **definido, sin implementar** (el detalle
> funcional se completa en su fase; este documento es el contrato previo).

## Responsabilidad
Selección y carga del prompt de cada comercio: lee las versiones publicadas en Bedrock
Prompt Management (base en `prompts/base/`, personalización en
`prompts/tenants/<tenant_id>/`), con fallback a la plantilla base, cacheo por versión,
rollback y rollout gradual. No contiene lógica de negocio ni decide la intención.

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
| Recurso | Por qué | Fase |
|---|---|---|
| Bedrock Prompt Management | Prompts versionados por operación y tenant | 5 |
| KMS (cifrado de prompts) | Manejo seguro de las plantillas personalizadas (uso exacto: TODO(verify)) | 5 |
| CloudWatch Logs | Cargas, caches, rollbacks y fallbacks con `tenant_id` | 5 |

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
| `PromptNotFound` | No existe plantilla para la operación/tenant | Fallback a la base + log warn |
| `PromptVersionCorrupt` | La versión pedida no es válida o está vacía | Fallback a la base + log error |
| `PromptServiceUnavailable` | Prompt Management no responde | Fallback a la base + log error |

## Cómo probarlo
- `tests/unit/`: fallback a la plantilla base, cache por versión y rollback con pin de
  versión.
- `tests/contract/`: el system prompt de un tenant nunca incluye prompts de otro tenant
  ni fragmentos de `prompts/tenants/` ajenos.
- `tests/agent_evals/datasets/`: operación sin personalización → se responde con la
  plantilla base y el tono del comercio sigue siendo correcto.
