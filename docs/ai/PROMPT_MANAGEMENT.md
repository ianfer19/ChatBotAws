# Gestión de prompts (por tenant)

Inventario, naming, versionado y publicación de los prompts de ChatBotAws en Amazon
Bedrock Prompt Management. El *cómo* se redacta cada prompt está en
[PROMPT_ENGINEERING.md](PROMPT_ENGINEERING.md).

## Inventario de prompts por tenant

Cada tenant tiene su propio set. La variante por defecto hereda de `prompts/base/`.

| Kind | Responsabilidad | Ruta base | Ruta por tenant |
|---|---|---|---|
| `system` | Identidad, jerarquía de instrucciones, límites, tono global, canary token | `prompts/base/system.md` | `prompts/tenants/<tenant_id>/system.md` |
| `greeting` | Saludo neutral de `greeting`/`smalltalk`: "Buenas, bienvenido a {comercio}, ¿en qué te ayudo?" sin enrutar a ventas | `prompts/base/greeting.md` | `prompts/tenants/<tenant_id>/greeting.md` |
| `sales` | Consultas de catálogo y productos; siempre con datos vía tools | `prompts/base/sales.md` | `prompts/tenants/<tenant_id>/sales.md` |
| `appointments` | Agendamiento y modificación de citas; confirma antes de escribir | `prompts/base/appointments.md` | `prompts/tenants/<tenant_id>/appointments.md` |
| `orders` | Consulta de estado de pedidos (solo lectura vía tools); nunca muta sin confirmación | `prompts/base/orders.md` | `prompts/tenants/<tenant_id>/orders.md` |
| `fallback` | Respuesta cuando no hay evidencia suficiente o un guardrail bloquea | `prompts/base/fallback.md` | `prompts/tenants/<tenant_id>/fallback.md` |
| `handoff` | Mensaje de traspaso a persona humana y marcado de `human_takeover` | `prompts/base/handoff.md` | `prompts/tenants/<tenant_id>/handoff.md` |

## Naming convencional

- Identificador: `{tenant_id}/{kind}` (p. ej. `comercio-demo/system`).
- `tenant_id`: slug en minúsculas, `[a-z0-9-]`, sin secretos ni datos reales.
- `kind`: exactamente uno de los siete de la tabla; no se crean kinds ad-hoc sin
  actualizar este documento y el inventario del slice `tenant_prompts`.
- El nombre publicado en Prompt Management es idéntico al del repo: cualquier
  desviación se detecta en la sincronización.

## Versionado semántico y aprobación

| Cambio | Versión | Aprobación |
|---|---|---|
| Rompe contrato de salida o cambia comportamiento esperado (mayores cambios de alcance) | MAJOR | Plataforma + dueño del comercio |
| Amplía alcance o ajusta tono sin romper evals | MINOR | 1 revisor de plataforma |
| Redacción, typo, formato sin cambio semántico | PATCH | 1 revisor de plataforma |

- Toda versión se publica con descripción y autor; la aprobación queda registrada
  en la revisión de código del repo y en los metadatos de la versión publicada.
- Los prompts de `prompts/base/` los aprueba el equipo de plataforma; los de
  `prompts/tenants/<tenant_id>/` los aprueba el dueño del comercio con visto
  bueno de plataforma.

## Flujo de rollout y rollback

```text
1. Editar plantilla en el repo (prompts/...)
2. Publicar en dev          -> versión nueva en Prompt Management
3. Correr evals             -> dataset de regresión (ver EVALUATION.md)
4. Promover a staging       -> misma versión, smoke tests
5. Promover a prod          -> pin de versión por tenant
6. Si falla en prod         -> rollback inmediato al pin anterior
```

- **Rollback**: nunca se edita "en caliente" prod; se vuelve a fijar (pin) la
  versión semántica anterior del mismo `{tenant_id}/{kind}` y se re-ejecutan las
  evals de regresión. `TODO(verify)` del procedimiento exacto de pin/promoción en
  Prompt Management.
- Un fallo de eval en cualquier etapa detiene el rollout (gate en CI).

## Personalización por tenant vs. plantilla base

| Capa | Quién la define | Contenido típico | Herencia |
|---|---|---|---|
| Plantilla base (`prompts/base/`) | Plataforma | Estructura, jerarquía, defensas, formatos | — |
| Personalización tenant (`prompts/tenants/`) | Comercio + plataforma | Tono, nombre del bot, horarios, reglas y políticas propias | Override parcial por `kind` |

Reglas de herencia:

- Si el tenant no tiene un `kind`, usa la base; si lo tiene, solo sobrescribe los
  bloques declarados (nunca reimplementa el system prompt completo).
- Las reglas de negocio (precios, stock, horarios efectivos) **no** se escriben en
  ninguna plantilla: el horario "de atención" en el prompt es texto orientativo y
  la hora real siempre sale de una tool.
- Prohibido en cualquier plantilla: secretos, tokens de acceso, credenciales y PII
  de clientes (el contexto con PII llega en runtime, no vive en el prompt).

## Quién edita qué

| Artefacto | Directorio | Editor |
|---|---|---|
| Plantillas base | `prompts/base/` | Equipo de plataforma (PR + revisión) |
| Personalización por tenant | `prompts/tenants/<tenant_id>/` | Dueño del comercio con revisión de plataforma |
| Sincronización con Prompt Management | `src/slices/tenant_prompts/` | Equipo de plataforma |
| Evals de regresión de prompts | `tests/agent_evals/datasets/` | Plataforma + responsable del tenant afectado |

El directorio `prompts/tenants/_example/` es la plantilla de referencia para crear
un tenant nuevo; nunca se publica tal cual.

## Sincronización repo <-> Prompt Management

El repo es el espejo local versionado; Prompt Management es la fuente de verdad en
runtime. El slice `tenant_prompts` se encarga de la sincronización:

1. **Push (repo -> Prompt Management)**: crea versión nueva por cada `{tenant_id}/{kind}`
   cambiado, con descripción y autor, y actualiza el pin de la variante activa.
2. **Pull (Prompt Management -> repo)**: trae cambios hechos en consola a un PR, para
   que pasen por evals y revisión.
3. **Drift check (CI)**: compara hash de plantilla local vs. versión publicada y
   falla si hay divergencia no versionada.

`TODO(verify)` de los nombres exactos de operaciones de la API de Bedrock Prompt
Management (crear prompt, crear versión, obtener, listar versiones, etc.) y de los
parámetros de activación por versión; verificar contra la documentación vigente
antes de implementar la Fase 5.

## Seguridad

- **Secretos**: nunca en prompts ni en metadatos de versiones; viven en variables de
  entorno y en IAM.
- **PII**: no se persiste PII de clientes en plantillas; el contexto personalizado
  se inyecta por turno y queda sujeto a retención (ver
  [MEMORY_AND_CONTEXT.md](MEMORY_AND_CONTEXT.md)).
- **Aislamiento**: cada tenant solo puede publicar y leer sus propios prompts;
  control de acceso por identidad y por recurso. `TODO(verify)` de los mecanismos
  de autorización de Prompt Management.
- **Auditoría**: toda publicación queda registrada (autor, versión, timestamp) y se
  revisa en las métricas de la Fase 9 (ver [EVALUATION.md](EVALUATION.md)).
