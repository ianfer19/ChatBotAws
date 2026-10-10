# RAG (conocimiento del comercio)

Recuperación aumentada sobre Aurora PostgreSQL Serverless v2 + pgvector. El slice
responsable es `knowledge_rag` (Paso 7).

## Alcance

**Sí** indexa conocimiento del comercio:

- Productos (descripción, atributos, categorías).
- Servicios ofrecidos.
- FAQ.
- Políticas del comercio (envíos, devoluciones, garantías).

**No** indexa información operacional transaccional. Precios vigentes, stock,
disponibilidad, estados de pedido y horarios efectivos **nunca** salen de RAG: esos
datos salen de tools y del backend legacy (ver
[MEMORY_AND_CONTEXT.md](MEMORY_AND_CONTEXT.md)). Si un chunk de RAG contradice al
sistema transaccional, gana el sistema transaccional.

## Ingesta

```text
Fuentes del legacy -> normalización por tenant -> chunking -> embeddings -> pgvector
```

1. **Fuentes**: catálogo, servicios, FAQ y políticas del backend legacy. Hoy el
   doble `KnowledgeSourcePort` está en `slices/knowledge_rag/infrastructure/
   in_memory/`; el adapter HTTP del legacy queda `TODO(verify)` hasta el Paso 11.
2. **Normalización por tenant**: cada documento se marca con `tenant_id`; nunca se
   ingiere un documento sin tenant asignado.
3. **Chunking**: por párrafo y por oración con solapamiento (`chunk_document`,
   `MAX_CHUNK_CHARS=1200` y `CHUNK_OVERLAP_CHARS=150` → `TODO(verify)`: calibrar
   con el dataset de evals).
4. **Embeddings**: `amazon.titan-embed-text-v1`, 1536 dimensiones (verificado con
   invocación real; coincide con `vector(1536)` de DATA_MODEL). La consulta se
   embeddea con el mismo modelo.
5. **Escritura**: `INSERT` con metadatos (`tenant_id`, `source_type`, `source_id`,
   `ingested_at`, hash del contenido) para poder auditar y purgar.

Re-ingesta idempotente por hash: un documento sin cambios no genera un chunk nuevo.

## Esquema resumido

Tablas principales (detalle completo en
[../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md); la migración
canónica es `infra/modules/aurora/migrations/001_knowledge.sql`):

| Tabla | Contenido clave |
|---|---|
| `documents` | `tenant_id`, `source_id`, `content_hash`, `ingested_at` (PK compuesta; idempotencia de re-ingesta) |
| `knowledge_chunks` | `tenant_id`, `chunk_id`, `source_type`, `source_id`, `title`, `content`, `embedding` (`vector(1536)`), `metadata` |

Índice HNSW por vector + filtro por `tenant_id` para que la búsqueda jamás cruce
tenants.

## Retrieval

| Parámetro | Regla | Valor inicial |
|---|---|---|
| Filtro `tenant_id` | **SIEMPRE**, antes de la similitud | — |
| `top_k` | Candidatos a recuperar | `TODO(verify)` (p. ej. 4–8) |
| Umbral de similitud | Descarta candidatos poco parecidos | `TODO(verify)` |

Reglas:

- La consulta se embeddea con el **mismo** modelo de la ingesta.
- Si el filtro por `tenant_id` se omite por error, es un bug de severidad alta:
  implica fuga entre tenants. Hay test de contrato para esto.
- El retrieval se expone como tool con schema, timeout e idempotencia, igual que
  el resto de tools (el LLM no consulta la BD directo).

## Post-proceso

- **Reranking** de los candidatos antes de construir la respuesta: opcional,
  `TODO(verify)` (modelo, coste y ganancia real con el dataset de evals).
- Deduplicación por similitud de texto para no repetir el mismo fragmento.
- Selección de fuentes: se priorizan documentos `policy`/`faq` frente a contenido
  generado por usuarios (ver [Anti-poisoning](#anti-poisoning)).

## Pasos de la respuesta

```text
1. Recuperar chunks (filtro tenant_id + similitud)      [grafo faq, nodo retrieve]
2. Construir la respuesta SOLO con los chunks recuperados [nodo respond]
3. Aplicar el guardrail de contextual grounding           [Paso 13, pendiente]
4. Si hay evidencia suficiente -> responder citando la fuente
   Si no la hay             -> mensaje de fallback del dominio (sin inventar)
```

- El grafo faq (`slices/knowledge_rag/application/graph.py`) implementa hoy los
  pasos 1, 2 y 4: `retrieve` → `respond` (con el bloque `<evidencia>` en el
  system y cita de fuente) o `fallback` (mensaje de `domain/rules.py`, sin
  invocar al modelo). El paso 3 llega con `ApplyGuardrail` en el Paso 13.
- El prompt de `sales`/`knowledge` recibe `grounding_source` = chunks y la
  respuesta se genera restringida a ese material (ver
  [GUARDRAILS.md](GUARDRAILS.md) para `grounding_source`, `query` y
  `guard_content`).
- Si los chunks están por debajo del umbral de similitud, no se responde "casi
  seguro": se usa el `fallback` o se escala a una persona.
- Citación corta del origen (nombre de la fuente/FAQ) cuando esté disponible en
  `metadata`.

## Anti-poisoning

| Control | Detalle |
|---|---|
| Quién puede ingerir | Solo procesos con identidad de plataforma y por `tenant_id`; el usuario final **nunca** ingeriría directo |
| Sanitización | Texto de origen usuario se sanea y se marca como no confiable; no se indexa sin revisión |
| Fuentes confiables | Catálogo, FAQ y políticas del comercio (`source_type` controlado) |
| Contenido de usuarios | Reseñas/comentarios: segregado, con `source_type` distinto y peso menor o excluido del retrieval de respuestas |
| Trazabilidad | `source_id` + `content_hash` por fuente para purgar en cuanto se detecta manipulación |
| Detección | Eval de poisoning y test de regresión (ver [EVALUATION.md](EVALUATION.md)) |

Una respuesta construida sobre un chunk envenenado es indetectable por el modelo:
por eso la ingesta y la separación de fuentes son el control real.

## Latencia y costos

- Presupuesto de latencia por turno: `TODO(verify)`; medir retrieval + generación +
  guardrail en el Paso 13.
- Embeddings de ingesta y de consulta, almacenamiento de pgvector y reranking
  tienen coste propio: `TODO(verify pricing)` antes de estimar el impacto de
  ampliar el catálogo o de re-ingestas frecuentes.
- Mitigaciones: caché de embedding por texto, re-ingesta solo por hash cambiado,
  `top_k` mínimo efectivo.
