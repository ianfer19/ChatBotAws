# Slice: knowledge_rag

> Paso de implementación: **Paso 7**. Estado: **definido, sin implementar** (el detalle
> funcional se completa en su paso; este documento es el contrato previo).

## Responsabilidad
Recuperación y respuesta fundamentada: busca los fragmentos relevantes del conocimiento
del comercio y entrega la evidencia con la que el agente responde. No redacta la
respuesta final (la arma el especialista), no guarda datos de negocio transaccionales
(eso es el legacy) y no decide la intención.

## Entradas y salidas
- Entradas: consultas del supervisor y de los especialistas mediante la tool
  `search_knowledge` o el contrato de `../../../shared/contracts/`, siempre con
  `tenant_id` y `correlation_id` del contexto resuelto.
- Salidas: lista de chunks con score y texto (evidencia para el grounding), verificada
  con el contextual grounding guardrail; logs de cobertura y fallback sin PII.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): la tool `search_knowledge` y
  los contratos `KnowledgeQuery` / `EvidenceChunk`.
- Consume: `VectorStorePort` (implementado por `adapters/aurora` con pgvector),
  `GuardrailPort` (implementado por `adapters/bedrock` con `ApplyGuardrail`) y los ports
  del propio domain (umbral de similitud, ingesta con anti-poisoning).

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| Aurora PostgreSQL + pgvector (`knowledge_chunks`) | Búsqueda semántica filtrada por `tenant_id` | 7 |
| Bedrock Guardrails (`ApplyGuardrail`) | Verificación de grounding de la respuesta | 13 |
| Modelo de embeddings en Bedrock | Vectorización de consultas y de los chunks | 2 |
| CloudWatch Logs | Trazas de retrieval, score y fallback con `correlation_id` | 7 |

## Reglas de negocio clave
1. El filtro `tenant_id` es obligatorio en toda query vectorial: sin excepción y sin
   posibilidad de omitirlo desde el payload del LLM.
2. Umbral de similitud para aceptar evidencia: TODO(verify) (se calibra con los evals).
3. Sin evidencia por encima del umbral → fallback "no tengo esa información"; el
   modelo nunca inventa una respuesta.
4. Toda respuesta con evidencia pasa por `ApplyGuardrail` con `grounding_source`,
   `query` y `guard_content`; la limitación de AWS para chatbot es TODO(verify) y se
   documenta en el ADR 0008 (ver `../../../docs/ai/GUARDRAILS.md`).
5. Anti-poisoning en la ingesta: solo se indexan fuentes autorizadas del tenant, con
   validación de origen y revisión previa; el LLM jamás escribe en la base.
6. La respuesta nunca incluye fragmentos de otro tenant (consecuencia de la regla 1,
   verificada en test).

## Tools expuestas al LLM
| Tool | Esquema resumido | Notas de seguridad |
|---|---|---|
| `search_knowledge` | `{query, top_k?}` → `[{chunk, score, source}]` | Solo lectura; `tenant_id` inyectado del contexto, no del payload; timeout y log con `correlation_id` |

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `NoEvidenceFound` | Ningún chunk supera el umbral | "No tengo esa información" + log info |
| `GuardrailBlocked` | El grounding rechaza la respuesta | Mensaje genérico de seguridad + log warn |
| `VectorStoreUnavailable` | Aurora/pgvector no responde | Respuesta sin RAG, degradada + log error |
| `IngestValidationFailed` | Origen no autorizado al indexar | No se indexa + log warn con `tenant_id` |

## Cómo probarlo
- `tests/unit/`: domain de `knowledge_rag` — fallback sin evidencia, umbral aplicado y
  filtro `tenant_id` imposible de saltar.
- `tests/contract/`: esquemas de `KnowledgeQuery`/`EvidenceChunk` y que el payload de la
  tool no admite un `tenant_id` arbitrario.
- `tests/agent_evals/datasets/`: pregunta fuera del catálogo del comercio → respuesta
  de fallback sin invención; pregunta con evidencia → respuesta con fuente citada.
