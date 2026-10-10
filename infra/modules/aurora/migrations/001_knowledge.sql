-- Migración inicial del conocimiento (Paso 7: RAG con pgvector).
--
-- Se aplica A MANO contra el endpoint del entorno desde dentro de la VPC
-- (ver ../README.md, sección "Migración inicial"): Terraform crea el clúster
-- y su extensión precargada, pero no ejecuta el esquema. Idempotente: se puede
-- re-ejecutar sin efecto (IF NOT EXISTS en todo).
--
-- El esquema `knowledge_chunks` es el de docs/architecture/DATA_MODEL.md; la
-- tabla `documents` añade la idempotencia de la re-ingesta por hash (docs/ai/
-- RAG.md): los ids de chunks NO se guardan aquí, se leen de knowledge_chunks.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    tenant_id    text        NOT NULL,
    source_id    text        NOT NULL,   -- id de la fuente en el backend legacy
    content_hash text        NOT NULL,   -- SHA-256 del contenido indexado la última vez
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source_id)
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    tenant_id    text        NOT NULL,
    chunk_id     uuid        NOT NULL DEFAULT gen_random_uuid(),
    source_type  text        NOT NULL,   -- product | service | faq | policy
    source_id    text        NOT NULL,   -- id en el backend legacy
    title        text,
    content      text        NOT NULL,
    embedding    vector(1536) NOT NULL,  -- amazon.titan-embed-text-v1 (verificado con invocación real)
    metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, chunk_id)
);

-- TODO(verify): HNSW frente a IVFFlat según volumen y coste de ingestión (DATA_MODEL).
CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- Apoyo al registro de documentos (ARRAY correlacionada) y al purgado por fuente.
CREATE INDEX IF NOT EXISTS knowledge_chunks_source_idx
    ON knowledge_chunks (tenant_id, source_id);
