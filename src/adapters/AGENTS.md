# AGENTS.md — `adapters/` (adapters transversales)

> Reglas generales del repo: [AGENTS.md](../../AGENTS.md) raíz. Este archivo solo cubre
> los adapters transversales.

## Responsabilidad

Implementaciones concretas de puertos contra servicios AWS y contra el backend legacy.
Cada subpaquete es un adapter: **traduce** un servicio externo al lenguaje del sistema
(errores tipados, modelos Pydantic, timeouts, reintentos) **sin contener reglas de negocio**
y sin importar `slices.*` (lo verifica import-linter en CI).

## Adaptadores

| Paquete | Servicio | Implementa | Paso |
|---|---|---|---|
| `in_memory/` | Sin servicio (dobles en memoria de puertos compartidos) | `DraftStorePort`, `VectorStorePort`, `EmbeddingsPort`, `MemoryStorePort` | 5, 7 y 8 |
| `checkpointer/` | LangGraph (checkpoints de conversación tras un port) | `PortCheckpointSaver(BaseCheckpointSaver[str])` + `thread_id_de` | 8 |
| `bedrock/` | Amazon Bedrock (modelos, embeddings, Guardrails, Prompt Management) | `shared.ports.LLMPort` + `EmbeddingsPort` (`BedrockEmbeddings`) + cliente de guardrails/prompt | 2, 7 y 13 |
| `agentcore/` | Bedrock AgentCore (Runtime, Memory, Gateway, Identity, Policy) | puertos de memoria/gateway | 10–12 |
| `dynamodb/` | DynamoDB (tablas operacionales) | puertos de persistencia de contexto/conversación/abuso + `MemoryStorePort` (`DynamoDBMemoryStore`) | 6 y 8 |
| `aurora/` | Aurora PostgreSQL v2 + pgvector (SOLO conocimiento) | `VectorStorePort` (búsqueda pgvector con `tenant_id`) | 7 |
| `s3/` | S3 (archivo conversaciones y media) | puertos de archivo | 6 |
| `sqs/` | Amazon SQS (cola de eventos del gateway) | `shared.ports.EventBusPort` (`SQSEventBus`: cuerpo `{event, payload}`, timeout y errores traducidos) | 9 |
| `comprehend/` | Amazon Comprehend (sentimiento) | `SentimentPort` de handoff | fuera de ruta |
| `legacy_backend/` | APIs HTTP del backend `sahagunonline/back` | puertos de negocio (pedidos, citas, catálogo) | 5 |

**Estado**: `bedrock/` está implementado desde el **Paso 2** — `BedrockLLM(LLMPort)` sobre la
Converse API, con `bedrock_model_id` (obligatorio) y `bedrock_timeout_seconds` de `Settings`;
desde el **Paso 7** añade `BedrockEmbeddings(EmbeddingsPort)` (`invoke-model` con
`bedrock_embeddings_model_id`, 1536 dims por defecto). `aurora/` está implementado desde el
**Paso 7**: `AuroraVectorStore` (pgvector, filtro `tenant_id` siempre presente, score
`1 - (embedding <=> vec)` recortado a [0,1]), `AuroraConnectionFactory` (secreto en
Secrets Manager, cacheado, psycopg traducido a `ToolError`) y
`AuroraDocumentRegistry` vive en `infrastructure/aurora.py` del slice `knowledge_rag`
(idempotencia de re-ingesta; regla: los adapters transversales no importan slices).
`in_memory/` existe desde el **Paso 5** (`InMemoryDraftStore`), desde el **Paso 7** añade
`InMemoryVectorStore` e `InMemoryEmbeddings` y desde el **Paso 8** `InMemoryMemoryStore`.
`checkpointer/` (Paso 8) traduce la API de `BaseCheckpointSaver` a las tres operaciones de
`MemoryStorePort` (solo el checkpoint más reciente, `thread_id = tenant#conversación`;
ADR 0013). `dynamodb/` está
implementado desde el **Paso 8** con `DynamoDBMemoryStore(MemoryStorePort)` (tabla
`chatbot_checkpoints`, claves `ORG#`/`CONV#`, TTL, errores traducidos). `sqs/` está
implementado desde el **Paso 9** con `SQSEventBus(EventBusPort)` (cola con DLQ vía
`infra/modules/sqs`, cuerpo `{event, payload}`, `ToolError`/`ToolTimeoutError` con
`event_name` en `details` y sin payload en logs) — las demás carpetas son esqueletos que
se rellenan en sus pasos. El cliente de Guardrails/Prompt Management llega en el Paso 13.

## Reglas

1. Un adapter = un paquete con `__init__.py` documentado; los clientes AWS (boto3) se
   crean **dentro** del adapter (inyección vía constructor/factory), nunca a nivel de módulo.
2. **Errores**: toda excepción del servicio externo se traduce a un error tipado de
   `shared/errors/` (jamás se fuga un `botocore.ClientError` al dominio).
3. **Timeout y reintentos** obligatorios en toda llamada de red; sin ellos el turno del
   chatbot puede colgarse.
4. **Logs**: cada llamada relevante loguea `correlation_id` y `tenant_id`; nunca credenciales
   ni payloads con PII completa.
5. **Sin APIs inventadas**: si un parámetro no está confirmado en la documentación de AWS,
   `TODO(verify)` en el código y en la doc correspondiente.
6. **Tenant**: el adapter recibe el `tenant_id` como argumento explícito; nunca lo infiere
   ni lo lee de un payload externo.

## Cómo añadir un adapter

1. Puerto (Protocol) en `shared/ports/` o en el `domain/` del slice que lo necesita.
2. Paquete nuevo aquí con `__init__.py` documentado, cliente, traducción de errores y tests
   unit mocks (sin AWS real).
3. Registro en la tabla anterior + en `infra/modules/` el recurso IAM/endpoint si aplica.

## Cómo probarlo

Unit con dobles inyectados por constructor (sin AWS real) en `tests/unit/`; integración real
en `tests/integration/` solo con credenciales de dev (marker `integration`, auto-omitido en CI).
El smoke del Paso 2 es `tests/integration/test_bedrock_smoke.py`.
