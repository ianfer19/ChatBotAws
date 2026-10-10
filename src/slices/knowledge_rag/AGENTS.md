# Slice: knowledge_rag

> Paso de implementación: **Paso 7**. Estado: **implementado (Fases 1–5)** — contratos
> y dominio (chunking, anti-poisoning, selección de evidencia), ingesta idempotente
> tras `KnowledgeSourcePort` (doble en memoria; HTTP legacy → `TODO(verify)` Paso 11),
> tool `search_knowledge`, adapters reales (`BedrockEmbeddings`,
> `AuroraVectorStore`/`AuroraConnectionFactory` + migración `001_knowledge.sql`),
> **grafo faq** (`retrieve` → `respond`/`fallback`) con su nodo `route_faq` en el
> supervisor, prompt `prompts/base/faq.md` y evals (`faq_behavior.json`). Pendiente en
> la ruta: `ApplyGuardrail` con `grounding_source` (Paso 13).

## Responsabilidad
Recuperación y respuesta fundamentada: indexa el conocimiento del comercio, busca los
fragmentos relevantes con filtro de tenant y **redacta la respuesta solo con esa
evidencia** (el grafo `faq` vive aquí). No guarda datos de negocio transaccionales
(eso es el legacy) y no decide la intención (eso es `supervisor`).

## Entradas y salidas
- Entradas: el turno desde `route_faq` (`tenant_id`, `correlation_id`,
  `user_message`, `history`, todos resueltos en el gateway); consultas de ingesta
  desde `KnowledgeSourcePort`.
- Salidas: `reply` fundamentado (con la fuente citada) o el mensaje honesto de
  fallback; `ToolResult` con la evidencia (score 0..1) para quién use la tool;
  logs de cobertura y fallback con `correlation_id` y `tenant_id`, sin el texto
  de la consulta (posible PII).

## Grafo (Paso 7)
- `application/graph.py` → `build_faq_graph(llm, embeddings, store, threshold=...)`.
  Nodos en `application/nodes/`: `retrieve` (ejecuta `search_knowledge` con los ids
  del estado; sin evidencia escribe `fallback_reason=sin_evidencia` y con el
  almacén caído `almacen_no_disponible`, ambos sin romper el turno),
  `respond` (system = plantilla `faq.md` + `TAREA_RESPONDER` + bloque
  `<evidencia>`; historial + pregunta como mensajes) y `fallback` (mensaje de
  `domain/rules.py::mensaje_fallback`, **cero invocaciones al modelo**).
  Arista condicional `ruta_tras_recuperar`: evidencia → `respond`; motivo →
  `fallback`.
- `AgentState` (`application/state.py`): el llamador pone `tenant_id`,
  `correlation_id` y `user_message`; el resto lo escriben los nodos.
- Una sola llamada al LLM por turno y **solo** con evidencia; el fallback jamás
  pasa por el modelo (hay test que cuenta las llamadas).
- Sin checkpointer (`TODO(decision)`: multi-turno con checkpointer en el Paso 8).

## Ports
- Expone (aplicación a otros slices vía shared/contracts): la tool
  `search_knowledge` y los contratos `KnowledgeQuery` / `EvidenceChunk`
  (`shared/contracts/rag.py`; la consulta **no admite `tenant_id`**: se inyecta
  del contexto).
- Consume: `VectorStorePort` (implementado por `adapters/aurora.AuroraVectorStore`
  con pgvector; doble `InMemoryVectorStore`), `EmbeddingsPort` (implementado por
  `adapters/bedrock.BedrockEmbeddings`; doble `InMemoryEmbeddings`),
  `LLMPort` (solo redacción), `GuardrailPort` (implementado por
  `adapters/bedrock` con `ApplyGuardrail`, Paso 13) y los ports del propio
  domain: `KnowledgeSourcePort` (fuente de documentos; doble en memoria, HTTP →
  `TODO(verify)` Paso 11) y `DocumentRegistryPort` (idempotencia por hash; hoy
  `infrastructure/in_memory.py`, el real es
  `infrastructure/aurora.py::AuroraDocumentRegistry`).

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| Aurora PostgreSQL + pgvector (`knowledge_chunks`, `documents`) | Búsqueda semántica filtrada por `tenant_id` + re-ingesta idempotente | 7 |
| Bedrock `amazon.titan-embed-text-v1` (1536 dims) | Vectorización de consultas y de los chunks | 2/7 |
| Bedrock Guardrails (`ApplyGuardrail`) | Verificación de grounding de la respuesta | 13 |
| CloudWatch Logs | Trazas de retrieval, score y fallback con `correlation_id` | 7 |

## Reglas de negocio clave
1. El filtro `tenant_id` es obligatorio en toda query vectorial: sin excepción y sin
   posibilidad de omitirlo desde el payload del LLM.
2. Umbral de similitud para aceptar evidencia: `SIMILITUDE_THRESHOLD=0.35`
   (`TODO(verify)`; se calibra con los evals).
3. Sin evidencia por encima del umbral → mensaje honesto de
   `domain/rules.py::mensaje_fallback`; el modelo nunca inventa una respuesta.
4. El LLM solo se invoca en la rama con evidencia; el fallback sale de código
   (test que falla si el fallback hace una llamada al modelo).
5. Toda respuesta con evidencia pasa por `ApplyGuardrail` con `grounding_source`,
   `query` y `guard_content` (Paso 13); la limitación de AWS para chatbot es
   `TODO(verify)` y se documenta en el ADR 0008 (ver
   `../../../docs/ai/GUARDRAILS.md`).
6. Anti-poisoning en la ingesta: solo se indexan fuentes autorizadas del tenant,
   con validación de origen (`ALLOWED_SOURCE_TYPES`) y revisión previa; el LLM
   jamás escribe en la base.
7. La respuesta nunca incluye fragmentos de otro tenant (consecuencia de la regla 1;
   verificada en test a nivel de tool **y** de grafo).

## Tools expuestas al LLM
| Tool | Esquema resumido | Notas de seguridad |
|---|---|---|
| `search_knowledge` | `{query, top_k?}` → `[{chunk, score, source}]` | Solo lectura; `tenant_id` inyectado del contexto, no del payload; timeout y log con `correlation_id` |

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `NoEvidenceFound` | Ningún chunk supera el umbral | "No tengo esa información..." (nodo `fallback`) + log info `knowledge_rag.sin_evidencia` |
| `VectorStoreUnavailable` | Aurora/pgvector o embeddings no responden | "No pude consultar la información..." + log error `knowledge_rag.almacen_no_disponible` |
| `GuardrailBlocked` | El grounding rechaza la respuesta (Paso 13) | Mensaje genérico de seguridad + log warn |
| `IngestValidationFailed` | Origen no autorizado al indexar | No se indexa + log warn `knowledge_rag.ingest_rechazado` |

## Cómo probarlo
- Unit (hecho): `tests/unit/test_knowledge_rag_rules.py` (chunking, hash,
  anti-poisoning, umbral/dedup y fallback sin inventar), `test_knowledge_rag_ingest.py`
  (idempotencia y rechazos), `test_knowledge_rag_tools.py` (evidencia citada,
  aislamiento por tenant, logs sin PII) y `test_knowledge_rag_graph.py` (ambas ramas
  del grafo, cero llamadas al LLM en fallback y aislamiento por tenant en el grafo
  completo).
- Unit adapters (hecho): `test_adapters_aurora_vector.py`,
  `test_adapters_aurora_documents.py`, `test_adapters_aurora_connection.py` (SQL con
  tenant, secreto cacheado, psycopg traducido a `ToolError`) y
  `test_adapters_bedrock_embeddings.py` (invoke_model, dimensionalidad y timeouts).
- Contract (hecho): `tests/contract/test_rag_contracts.py` — esquemas de
  `KnowledgeQuery`/`EvidenceChunk` y que el payload no admite un `tenant_id`
  arbitrario.
- Eval (hecho): `tests/agent_evals/datasets/faq_behavior.json` + su ejecutor
  `test_faq_dataset.py` — `grounding_01` (fuera del conocimiento → fallback sin
  invención), respuesta con fuente citada y `tenant_isolation_01` (la misma
  pregunta solo ve los chunks del propio comercio).
