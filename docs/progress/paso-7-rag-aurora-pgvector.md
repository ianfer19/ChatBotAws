# Progreso — Paso 7: RAG + Aurora/pgvector

> **Checklist vivo del Paso 7.** Se actualiza tras cada commit de la fase: `[x]` hecho,
> `[~]` en curso, `[ ]` pendiente. Es la respuesta rápida a «¿qué se hizo y qué falta?»
> sin releer el código. Criterio de cierre del paso:
> [ROADMAP §1 fila 7](../ROADMAP.md).
>
> **Estado global: PASO 7 COMPLETO (5/5 fases); siguiente: Paso 8 (Memory / checkpoints).**

## Decisiones cerradas con el usuario (2026-10-09)

- [x] Cliente PostgreSQL: **`psycopg[binary]`** (sin compilación local; dobles en
      memoria para tests y evals).
- [x] Alcance del grafo: **grafo `faq` completo** (slice `knowledge_rag`) + nodo
      `route_faq` en el supervisor; `sales` sigue cayendo en `route_pending`
      (grafo propio fuera de la ruta).
- [x] Ingesta: `KnowledgeSourcePort` en `domain/` + doble en memoria;
      el adapter HTTP del legacy queda `TODO(verify)` para el Paso 11.
- [x] Umbrales de similitud/umbral de evidencia: `SIMILITUDE_THRESHOLD=0.35` con
      `TODO(verify)` (se calibra con los evals).

## Fase 1 — contratos RAG, EmbeddingsPort y dominio  (commiteada `8fefc6c`)

- [x] `shared/contracts/rag.py`: `KnowledgeQuery` (sin `tenant_id` — se inyecta
      del contexto) y `EvidenceChunk` (score 0..1); contract test que rechaza un
      `tenant_id` arbitrario en el payload.
- [x] `shared/ports/embeddings.py`: `EmbeddingsPort` (`runtime_checkable`).
- [x] `knowledge_rag/domain/`: entidades (`KnowledgeDocument`, `KnowledgeChunk`),
      puertos (`KnowledgeSourcePort`, `DocumentRegistryPort`), reglas
      (`chunk_document`, `content_hash`, anti-poisoning con
      `ALLOWED_SOURCE_TYPES`, `select_evidence`, `mensaje_fallback`) y errores
      tipados (`NoEvidenceFound`, `IngestValidationFailed`,
      `VectorStoreUnavailable`, `GuardrailBlocked`).

## Fase 2 — ingesta idempotente + tool `search_knowledge`  (commiteada `e121ef5`)

- [x] `application/ingest.py`: flujo validar origen → chunking → embeddings →
      upsert idempotente por `content_hash` (documento sin cambios → 0 chunks).
- [x] `application/tools.py` + `schemas.py`: tool `search_knowledge`
      (`tenant_id` inyectado, `top_k`, timeout y log con `correlation_id`, sin
      PII en el log).
- [x] Dobles en memoria: `adapters/in_memory/{vector,embeddings}.py`
      (`InMemoryVectorStore`, `InMemoryEmbeddings` — hash de bolsa de palabras
      determinista) y `knowledge_rag/infrastructure/in_memory.py`
      (fuente y registro de documentos).

## Fase 3 — adapters reales bedrock embeddings + aurora  (commiteada `e510b6b`)

- [x] `adapters/bedrock/embeddings.py`: `BedrockEmbeddings(EmbeddingsPort)` vía
      `invoke-model` (`amazon.titan-embed-text-v1`, 1536 dims verificados con
      invocación real), timeouts y traducción a `ToolError`.
- [x] `adapters/aurora/`: `connection.py` (Secrets Manager cacheado, psycopg
      traducido a `ToolError`, `Connection[tuple[Any, ...]]`), `vector.py`
      (`AuroraVectorStore`: filtro `tenant_id` siempre presente, score
      `1 - (embedding <=> vec)` recortado a [0,1]) y tests con SQL asertado.
- [x] `knowledge_rag/infrastructure/aurora.py`: `AuroraDocumentRegistry`
      (idempotencia de re-ingesta; el registro vive en el slice por la regla
      de que `adapters/` no importa slices).
- [x] `infra/modules/aurora/migrations/001_knowledge.sql`: `documents`
      (PK `tenant_id`+`source_id`, hash) y `knowledge_chunks`
      (PK `tenant_id`+`chunk_id`, `vector(1536)`, índice HNSW) — aplicación
      manual documentada en el README del módulo.
- [x] `Settings`: `bedrock_embeddings_model_id`/`_dimensions` y
      `aurora_host`/`_port`/`_dbname`/`_username`/`_secret_arn`.

## Fase 4 — grafo faq + route_faq + evals  (commiteada `4660e75`)

- [x] Grafo `faq` (`application/graph.py`): `retrieve` →
      `ruta_tras_recuperar` → `respond` | `fallback`; evidencia + cita de
      fuente con el bloque `<evidencia>` en el system (`application/prompts.py`
      + `prompts/base/faq.md`); fallback con **cero** invocaciones al modelo y
      mensajes de `domain/rules.py::mensaje_fallback` (`sin_evidencia` y
      `almacen_no_disponible`).
- [x] Supervisor: nodo `route_faq` (espejo de `route_orders`, sin
      `conversation_id`), `Deps.faq_graph` opcional y `ruta_tras_decidir` que
      solo manda a `route_faq` si el grafo está inyectado (retrocompatible).
- [x] Tests: `test_knowledge_rag_graph.py` (ambas ramas, aislamiento por tenant
      en el grafo completo, fallo de almacén, mensajes de fallback) y 3 tests
      nuevos en `test_supervisor_graph.py` (invocación, degradación y
      `ruta_tras_decidir`).
- [x] Evals: `tests/agent_evals/datasets/faq_behavior.json` + ejecutor
      `test_faq_dataset.py` — `grounding_01` (fuera del conocimiento →
      fallback sin invención), respuesta con fuente citada (y sin ver el
      horario de otro tenant) y `tenant_isolation_01`.

## Fase 5 — documentación y cierre  (en curso)

- [x] `docs/ai/RAG.md`: esquema real (`documents`/`knowledge_chunks` con
      `source_id`), chunking y embeddings implementados, mapa de los pasos de
      la respuesta al grafo faq.
- [x] AGENTS: `knowledge_rag` (contrato → implementado, sección del grafo),
      `supervisor` (`route_faq`), `adapters` (aurora/bedrock embeddings/
      in_memory), `shared` (puertos, contratos y settings del Paso 7), índice
      de `src/slices/` y §1/§10 del AGENTS raíz → **hecho**; `CLAUDE.md` paso
      activo → 8; `tests/agent_evals/README.md` con `faq_behavior`.
- [x] Este checklist.
- [x] Batería completa en verde (ruff, format, mypy, pytest, lint-imports,
      terraform fmt, final_review, pyrefly).

## Criterios de hecho del ROADMAP (§1 fila 7)

- [x] **Respuesta fundamentada con grounding**: el grafo faq solo redacta con
      evidencia recuperada (bloque `<evidencia>` + cita de fuente); sin
      evidencia responde el mensaje honesto de `domain` sin invocar al modelo
      (eval `grounding_01`). El check de grounding de Bedrock Guardrails llega
      en el Paso 13 (`ApplyGuardrail`, `GuardrailBlockeado` ya definido).
- [x] **Test de aislamiento por tenant**: a nivel de tool
      (`test_knowledge_rag_tools.py`), de grafo (`test_knowledge_rag_graph.py`)
      y e2e (`tenant_isolation_01` en `faq_behavior.json`): la misma pregunta
      solo ve los chunks del propio comercio.
- [x] Batería completa en verde al cierre de la Fase 5.

## Pendientes explícitos (no bloquean el cierre)

- `TODO(verify)`: adapter HTTP de fuentes del legacy (Paso 11), HNSW vs IVFFlat
  según volumen, tamaño de chunk calibrado con evals, umbral de similitud.
- Guardrails con `grounding_source`: Paso 13. Prompt por tenant en Bedrock
  Prompt Management: fuera de la ruta.
