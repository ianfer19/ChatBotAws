# Visión general de la arquitectura

Documento de la Fase 1 (esqueleto y documentación). Describe el sistema tal como se prevé
construirlo; cada componente indica la fase que lo entrega. Todo dato de AWS no confirmado
aparece como `TODO(verify)`.

## Propósito del sistema

ChatBotAws es la plataforma de chatbot multi-comercio (multi-tenant) de Sahagún Online
(Colombia). Atiende conversaciones de clientes finales en WhatsApp, Instagram y Messenger
usando:

- **Orquestación** con LangGraph: estado, nodos, aristas condicionales, checkpoints y
  confirmación humana.
- **Modelo de lenguaje** en Amazon Bedrock detrás de un port intercambiable (`LLMPort`),
  con Bedrock Guardrails y prompts versionados por tenant en Bedrock Prompt Management.
- **Almacenamiento separado por naturaleza**: conocimiento en Aurora PostgreSQL Serverless
  v2 + pgvector; datos operacionales en DynamoDB; archivo de conversaciones y media en S3.
- **Sustitución gradual del orquestador legacy** del repo hermano `sahagunonline/back`
  (AWS SAM, ~35 Lambdas, DynamoDB single-table, Cognito, webhook Meta → SQS → orquestador
  LangGraph). El legacy sigue vivo hasta el corte, comercio por comercio (decisión D1).

Volumen inicial: 3 comercios heredados de la plataforma legacy; el chatbot todavía tiene
0 usuarios, así que se optimiza por claridad y coste bajo antes que por escala.

## Actores

| Actor | Qué hace | Qué espera del sistema |
|---|---|---|
| Cliente final | Escribe al comercio por WhatsApp, Instagram o Messenger | Respuesta útil y rápida; jamás ver datos de otro comercio |
| Comercio / operador | Define catálogo, prompts, horarios y reglas | Que el bot respete su marca, sus precios y sus políticas |
| Agente humano | Atiende los casos escalados (sentimiento negativo o petición explícita) | Recibir la conversación con contexto completo y trazabilidad |
| Desarrollador | Implementa slices, módulos Terraform, tests y evals | Estructura predecible, contratos estables, logs con `correlation_id` y `tenant_id` |

## Componentes y su mapa en el repositorio

### Kernel y adaptadores

| Componente | Responsabilidad | Carpeta | Fase |
|---|---|---|---|
| Kernel compartido | `errors`, `logging` (JSON), `config`, `context`, `contracts`, `ports` (`LLMPort`, `ClockPort`, `EventBusPort`) | `src/shared/` | 2 |
| Adaptadores de plataforma | Bedrock, AgentCore, DynamoDB, Aurora, S3, Comprehend, backend legacy | `src/adapters/` | 4 |
| Infraestructura | Módulos Terraform reutilizables (`state`, `network`, `aurora`, `dynamodb`, `s3`, `lambda`, `apigw`, `bedrock`, `agentcore`, `iam`, `observability`) | `infra/modules/` | 3 |
| Entornos | `dev`, `staging`, `prod` con estado remoto S3 + lock | `infra/envs/` | 3 |
| Prompts | Espejo local de las plantillas versionadas en Bedrock Prompt Management | `prompts/` | 5 |
| Tests | `unit`, `integration`, `contract`, `agent_evals` | `tests/` | 2+ |

### Slices (funcionalidad de punta a punta)

| Slice | Responsabilidad | Fase |
|---|---|---|
| `conversation_gateway` | Webhook Meta completo: verificación `hub.challenge`, validación de firma `X-Hub-Signature-256`, resolución de `tenant_id` y encolado en SQS; adapters de canal tras `ChannelPort` | 4 |
| `supervisor` | Grafo LangGraph: enrutado de intenciones, saludo/smalltalk, agente de ventas, confirmación humana | 4 |
| `customer_context` | Contexto del cliente por turno vía tool `get_customer_context` | 4 |
| `tenant_prompts` | Prompts versionados y aislados por `tenant_id` | 5 |
| `knowledge_rag` | Recuperación (chunks + embeddings) sobre Aurora con grounding | 5 |
| `appointments` | Citas y disponibilidad; tools hacia el backend legacy | 6 |
| `orders` | Pedidos y reglas de negocio, incluida la negativa a modificar horas | 6 |
| `sentiment_handoff` | Sentimiento con Comprehend y escalamiento a agente humano | 7 |
| `abuse_protection` | Límites de uso y bloqueos con TTL | 7 |
| `media_handling` | Imágenes y audios en S3 | 7 |
| `retention_archiving` | Archivo y borrado; cierra ADR 0007 | 7 |

Cada slice vive en `src/slices/<nombre>/` con `domain/`, `application/`, `infrastructure/`,
`handler/` y su `AGENTS.md`. El detalle está en [HEXAGONAL_AND_SLICING.md](HEXAGONAL_AND_SLICING.md).

## Flujo end-to-end de un mensaje (resumido)

1. Meta llama al webhook en API Gateway; `conversation_gateway` responde `hub.challenge`,
   valida la firma y descarta lo que no pase la verificación.
2. El gateway resuelve el `tenant_id` a partir del mapeo de canal replicado del legacy
   (`WA_CONFIG` / `IG_CONFIG` / `FB_CONFIG`, decisión D5) y encola el mensaje en SQS con
   `tenant_id` y `correlation_id`.
3. El `supervisor` consume el mensaje y enruta la intención con una arista condicional:
   `greeting` / `smalltalk` tiene ruta propia; los casos comerciales van al agente.
4. Cada turno de LangGraph se construye con (a) el contexto del cliente recuperado por la
   tool `get_customer_context` y (b) el historial de la conversación con ventana controlada
   y resumen al superar el límite.
5. El agente usa tools que llaman APIs HTTP del backend legacy vía AgentCore Gateway +
   Policy, y `knowledge_rag` recupera chunks de Aurora; la respuesta candidata pasa por
   Guardrails (`ApplyGuardrail` con grounding) antes de enviarse.
6. Comprehend evalúa el sentimiento; si es negativo o el cliente pide una persona, hay
   handoff a agente humano con el contexto de la conversación.

El detalle completo, incluidas las ramas de saludo y de handoff, está en el diagrama
[`diagrams/03-message-flow.mmd`](diagrams/03-message-flow.mmd).

## Requisitos funcionales clave

- **Multi-tenancy y prompts por tenant**: `tenant_id` = `store_id` del legacy (string
  legible tipo `"Sede_Elite_01"`); viaja en todo el contexto, separa datos y define qué
  versión de prompt aplica.
- **Saludo**: la intención `greeting` / `smalltalk` tiene ruta propia en el supervisor y
  responde de forma neutral: "Buenas, bienvenido a {comercio}, ¿en qué te ayudo?", sin
  enrutar al agente de ventas.
- **Contexto por turno**: cada turno incluye contexto de cliente e historial con ventana
  controlada y resumen; hay un test que falla si el prompt llega sin ellos.
- **Retención de conversaciones y media**: pendiente de decisión; se cierra en la Fase 7
  con los casos de uso ([ADR 0007](../adr/0007-retencion-de-conversaciones-y-media.md),
  estado Pendiente).
- **Handoff por sentimiento**: escalamiento a humano con contexto, no solo con el último
  mensaje.
- **Protección contra abuso**: límites por cliente/comercio con TTL y bloqueo temporal.
- **Guardrails**: contextual grounding con `grounding_source` (chunks), `query` (pregunta)
  y `guard_content` (respuesta); umbrales entre 0 y 0.99; al bloquear, respuesta de fallback
  y log con `correlation_id`. La documentación de AWS no marca "chatbot / QA conversacional"
  como caso soportado explícitamente, así que queda registrado en ADR 0008 con
  `TODO(verify)` (ver [../adr/README.md](../adr/README.md)).
- **AgentCore**: no es una alternativa a LangGraph; AgentCore ejecuta LangGraph. Adopción
  modular en la Fase 8, en orden Runtime → Memory → Gateway → Identity + Policy, activando
  solo lo que resuelva una necesidad real (decisión D4).

## Reglas de seguridad transversales

- El LLM **nunca** es fuente de verdad de precios, stock, disponibilidad, estados de pedido
  ni horas: esos datos salen de tools autorizadas o del catálogo replicado.
- Las reglas de negocio viven en `domain/`, nunca dentro de prompts.
- Ejemplo canónico de defensa en profundidad — el chatbot no puede modificar la hora de un
  pedido: (1) la tool no existe para el LLM, (2) el dominio `Order` rechaza el cambio,
  (3) AgentCore Policy deniega la acción, (4) el tema queda denegado en Guardrails,
  (5) test de regresión. Se desarrolla en [HEXAGONAL_AND_SLICING.md](HEXAGONAL_AND_SLICING.md).
- Amenazas cubiertas por diseño y por tests: prompt injection directa e indirecta, prompt
  poisoning en RAG, prompt leaking, jailbreaking, denial of wallet, bots externos (p. ej.
  Tigo) y fuga entre tenants.

## Cómo leer este repo

1. [`../../AGENTS.md`](../../AGENTS.md) — convenciones, comandos y reglas para humanos y agentes.
2. [HEXAGONAL_AND_SLICING.md](HEXAGONAL_AND_SLICING.md) — reglas de dependencia y estructura de slices.
3. [../adr/README.md](../adr/README.md) — decisiones registradas y su estado.
4. [DATA_MODEL.md](DATA_MODEL.md) — qué vive en Aurora, DynamoDB y S3.
5. Hermanos de este documento: [MULTI_TENANCY.md](MULTI_TENANCY.md),
   [INTEGRATION_WITH_LEGACY.md](INTEGRATION_WITH_LEGACY.md) y
   [AGENTCORE.md](AGENTCORE.md) profundizan en aislamiento por tenant, convivencia con el
   legacy y adopción modular de AgentCore.

## Diagrama

![Vista general](diagrams/01-overview.mmd)
