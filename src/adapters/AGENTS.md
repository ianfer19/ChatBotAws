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
| `bedrock/` | Amazon Bedrock (modelos, Guardrails, Prompt Management) | `shared.ports.LLMPort` + cliente de guardrails/prompt | 2 y 13 |
| `agentcore/` | Bedrock AgentCore (Runtime, Memory, Gateway, Identity, Policy) | puertos de memoria/gateway | 10–12 |
| `dynamodb/` | DynamoDB (tablas operacionales) | puertos de persistencia de contexto/conversación/abuso | 6 |
| `aurora/` | Aurora PostgreSQL v2 + pgvector (SOLO conocimiento) | `VectorStorePort` de RAG | 7 |
| `s3/` | S3 (archivo conversaciones y media) | puertos de archivo | 6 |
| `comprehend/` | Amazon Comprehend (sentimiento) | `SentimentPort` de handoff | fuera de ruta |
| `legacy_backend/` | APIs HTTP del backend `sahagunonline/back` | puertos de negocio (pedidos, citas, catálogo) | 5 |

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

Unit con mocks (moto/`TODO(verify)` de herramienta) en `tests/unit/`; integración real en
`tests/integration/` solo con credenciales de dev.
