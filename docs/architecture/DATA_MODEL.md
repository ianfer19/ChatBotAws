# Modelo de datos

Documento de la Fase 1. Un almacén por naturaleza de dato: conocimiento (Aurora + pgvector),
operacional (DynamoDB) y archivo (S3). Todo lo marcado `TODO(verify)` es un parámetro o
mecanismo de AWS que debe confirmarse antes de implementar.

## Principios

- Separación dura: el conocimiento no se mezcla con el estado operacional ni con el archivo.
- **Invariante transversal: toda query filtra por `tenant_id`.** En DynamoDB la clave de
  partición lo garantiza; en Aurora se exige `WHERE tenant_id = $1` (RLS como refuerzo,
  `TODO(verify)`); en S3 el prefijo. Ninguna lectura ni escritura cruza comercios.
- El LLM no es fuente de verdad: lee por tools y RAG, nunca escribe en estas tablas.
- La retención final de conversaciones y media está pendiente:
  [ADR 0007](../adr/0007-retencion-de-conversaciones-y-media.md) (estado Pendiente).

## Aurora PostgreSQL Serverless v2 + pgvector — conocimiento

| Qué va | Qué NO va | Por qué |
|---|---|---|
| Productos, servicios, FAQ y políticas por `tenant_id`, troceados y con embedding; metadatos de ingesta (origen, versión, fecha) | Conversaciones, contexto de cliente, pedidos, citas, límites de abuso, cualquier PII operacional | El RAG necesita búsqueda semántica aislada por tenant; el estado operacional necesita latencia baja y TTL, que Aurora no da |
| Réplica del catálogo del backend legacy para recuperación (decisión D2) | Escrituras en runtime desde el chatbot | El catálogo es copia de lectura; la verdad operativa (precio en vivo, stock) vive en el backend legacy y llega por tools |
| Filas del propio tenant | Cualquier fila de otro `tenant_id` | El aislamiento es un invariante, no una comprobación opcional: sin coincidencia de `tenant_id` no hay resultado |

### Esquema propuesto

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
    tenant_id    text        NOT NULL,
    chunk_id     uuid        NOT NULL DEFAULT gen_random_uuid(),
    source_type  text        NOT NULL,   -- product | service | faq | policy
    source_id    text        NOT NULL,   -- id en el backend legacy
    title        text,
    content      text        NOT NULL,
    embedding    vector(1536) NOT NULL,  -- TODO(verify): dimensionalidad según el modelo de Bedrock elegido
    metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, chunk_id)
);

-- TODO(verify): HNSW frente a IVFFlat según volumen y coste de ingestión
CREATE INDEX knowledge_chunks_embedding_idx
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
```

- **Solo lectura en runtime**: el flujo del chatbot consulta; las escrituras ocurren
  únicamente en la ingesta.
- **Ingesta desde el legacy**: `TODO(verify)` del mecanismo (¿evento del backend?, ¿job
  programado?, ¿CDC sobre las tablas legacy?). Cada corrida debe reemplazar los chunks del
  `tenant_id` afectado de forma atómica.
- Búsqueda por tenant siempre: `WHERE tenant_id = $1 ORDER BY embedding <=> $2`.

## DynamoDB — datos operacionales

| Qué va | Qué NO va | Por qué |
|---|---|---|
| Conversaciones recientes y sus mensajes, contexto del cliente, mapeo canal → tenant, límites de abuso y bloqueos, auditoría de tools | Catálogo, FAQ, políticas, embeddings, archivo histórico | Acceso por clave con latencia baja y coste predecible; el conocimiento necesita búsqueda vectorial que DynamoDB no ofrece |
| Estado vivo con expiración controlada (TTL) | Documentos grandes de conversación completa | Lo que pasa de la ventana va a S3, no crece aquí |

### Tablas y claves propuestas

| Tabla (por ambiente) | PK | SK | TTL | Contenido |
|---|---|---|---|---|
| `chatbot_conversations` | `ORG#<tenant_id>` | `CONV#<conversation_id>` y `MSG#<conversation_id>#<tsISO>` | atributo `ttl` en mensajes | Cabecera de conversación (canal, estado, `started_at`, `last_message_at`) y ventana reciente de mensajes |
| `chatbot_customer_context` | `ORG#<tenant_id>` | `CUSTOMER#<customer_id>` | `ttl` en datos volátiles | Resumen de contexto que la tool `get_customer_context` devuelve por turno |
| `chatbot_channel_mapping` | `WA_CONFIG#<phone_number_id>` (o `IG_CONFIG#…` / `FB_CONFIG#…`) | `ORG#<tenant_id>` | no expira | Réplica del mapeo de canal del legacy; decisión D5 |
| `chatbot_abuse_limits` | `ORG#<tenant_id>` | `LIMITS#<customer_id>` | `ttl` | Contadores por ventana, `blocked_until`, motivo |
| `chatbot_tool_audit` | `ORG#<tenant_id>` | `TOOL#<tsISO>#<tool_name>` | `ttl` según retención | Quién llamó qué tool, con qué argumentos y resultado |

El prefijo `ORG#<tenant_id>#` se hereda del patrón single-table del legacy para que el
test de contrato de claves sea único y para respetar la regla de filtrado de
[MULTI_TENANCY.md](MULTI_TENANCY.md) (sección 4). Las tablas se podrían consolidar en una
single-table por ambiente más adelante; el esquema propuesto prioriza legibilidad en la
Fase 1.

- **TTL de DynamoDB**: atributo numérico `ttl` en epoch seconds; el ítem se elimina de
  forma automática después de expirar (`TODO(verify)`: ventana real de borrado y encaje con
  los plazos de retención).
- **Mapeo canal → tenant**: replicado del legacy; `TODO(verify)` del mecanismo de
  sincronización (¿evento?, ¿replicación periódica?, ¿lectura perezosa con caché?) y de qué
  pasa cuando un comercio se da de baja o cambia de número.
- **Auditoría de tools**: imprescindible para detectar intentos de abuso y para depurar
  respuestas con `correlation_id`.
- **Streams**: reservados para el pipeline de retención/archivo cuando ADR 0007 se cierre
  (ver ADR 0002); `TODO(verify)` de si se usan en las tablas de conversación.
- **Por qué no va conocimiento aquí**: DynamoDB no busca por similitud; meter chunks con
  embeddings obligaría a escanear y a duplicar la verdad del catálogo.

## S3 — archivo de conversaciones y media

| Qué va | Qué NO va | Por qué |
|---|---|---|
| Conversaciones completas en JSONL, imágenes y audios enviados/recibidos | Secretos, claves, datos vivos de sesión, embeddings | Retención larga a bajo costo, con lifecycle y cifrado |
| Mismo prefijo de tenant para todo | Objetos sin clasificar de tenant | El aislamiento se garantiza por prefijo y por política IAM |

### Estructura propuesta

```text
s3://<bucket-archivo>/
├── <tenant_id>/conversations/YYYY/MM/DD/<conversation_id>.jsonl
└── <tenant_id>/media/<message_id>.<ext>
```

- **Formato de archivo de conversación**: JSONL, una línea por evento
  (`message_in`, `message_out`, `handoff`, `guardrail_block`, `tool_call`) con
  `correlation_id`, `tenant_id`, `channel`, `ts` y `role`. Propuesto, no cerrado:
  `TODO(verify)` del esquema definitivo al cerrar ADR 0007.
- **Media con el MISMO plazo que las conversaciones**, según el requisito: la misma regla
  de lifecycle debe cubrir ambos prefijos para que no queden imágenes huérfanas.
- **Lifecycle**: `TODO(verify)` del límite de reglas de lifecycle por bucket y de los
  tiempos mínimos de transición; los plazos concretos saldrán de ADR 0007.
- **KMS**: cifrado en reposo con llave gestionada por ambiente (SSE-KMS, `TODO(verify)`
  de la política de rotación y quién rota).
- **Bloqueo público**: Block Public Access activado y bucket solo accesible desde las
  identidades del sistema; ninguna URL de objeto es pública.

## Invariante y pendientes

1. **Todo dato lleva `tenant_id`** y toda operación lo filtra; es el contrato que revisan
   los tests de contrato en `tests/contract/`.
2. **Retención pendiente**: los plazos de conversaciones, media, TTL de DynamoDB y
   lifecycle de S3 se cierran juntos en la Fase 7 con los casos de uso
   ([ADR 0007](../adr/0007-retencion-de-conversaciones-y-media.md)).
3. Cualquier cambio de este documento requiere un ADR nuevo o la actualización del
   existente en [../adr/README.md](../adr/README.md).
