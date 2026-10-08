# ROADMAP — ruta de implementación de ChatBotAws

> Ruta acordada el 2026-10-07. Es la referencia activa de orden de trabajo; la lista de
> fases históricas (1–9) queda mapeada en la sección 3. Reglas generales: [AGENTS.md](../AGENTS.md);
> arquitectura: [architecture/OVERVIEW.md](architecture/OVERVIEW.md).

**Principio rector de la ruta**: LangGraph → abstracción de modelo (`LLMPort`) →
Bedrock → modelo. El agente **nunca** habla con Claude ni con ningún modelo directamente;
cambia el `modelId` de `BEDROCK_MODEL_ID` sin tocar los agentes. El modelo **nunca** es
fuente de verdad: la disponibilidad, los precios y el estado salen de tools validadas.

## 1. Los 14 pasos

| # | Paso | Entregables | Hecho cuando… |
|---|---|---|---|
| 1 | **Arquitectura/base** | `docs/ROADMAP.md`; ports (`LLMPort` firma Converse, `VectorStorePort`, `MemoryStorePort`, `AppointmentRepositoryPort`, `OrderRepositoryPort`); `boto3` + `langgraph` en dependencias | Batería completa en verde con los ports y sus dobles |
| 2 | **Bedrock + abstracción de modelos** | `src/adapters/bedrock/BedrockLLM(LLMPort)` con **Converse API**; `BEDROCK_MODEL_ID` en `Settings`; smoke test | Un `Python → BedrockLLM → Converse → modelo → respuesta` pasa con credenciales reales (sin ellas, el test se omite) |
| 3 | **LangGraph (grafo de citas)** | Grafo en `slices/appointments/application/` (nodos: understand → validate → need_more? → select_action → call_tool → validate_result → needs_confirmation? → respond) + `AgentState(TypedDict)` | El grafo corre end-to-end con `LLMPort` y repositorios falsos; tests de nodo |
| 4 | **Supervisor + customer_context** | Routing de intenciones, ruta propia de saludo (regresión obligatoria) y tool `get_customer_context` obligatoria por turno | Test: saludo nunca enruta a ventas; test: turno sin contexto o sin historial falla |
| 5 | **Tools + lógica de negocio** | `appointments/domain` y `orders/domain` (solapes, horario, confirmación); tools con schema; `AppointmentRepository` con doble en memoria; allowlist por tenant (LangGraph decide si puede usarla) | Unit de dominio + eval «sin hora → pide confirmación» en verde; adapter legacy **pendiente** de `catalogo_endpoints.md` |
| 6 | **Infraestructura Terraform base** | `state`, `network`, `dynamodb`, `s3`, `aurora`, `iam`, `apigw`, `lambda` (dev/staging/prod) | `terraform fmt` + `validate` en verde; hasta aquí, los stores de los pasos 3–5 son dobles en memoria |
| 7 | **RAG + Aurora/pgvector** | Slice `knowledge_rag`; `VectorStorePort` → `adapters/aurora`; chunking/embeddings | Respuesta fundamentada con grounding; test de aislamiento por tenant |
| 8 | **Memory / checkpoints** | Checkpointer de LangGraph (DynamoDB) tras port; políticas de ventana + resumen; ADR 0007 | La conversación sobrevive a invocaciones distintas; sin fuga de estado entre invocaciones |
| 9 | **Conversation gateway** | Webhook Meta (verificación `hub.challenge`, firma `X-Hub-Signature-256`, resolución de `tenant_id`, SQS) tras `ChannelPort` | Prueba con tráfico real de los 3 canales; deduplicación y aislamiento por tenant |
| 10 | **AgentCore Runtime** | Mismo grafo en Runtime (+ Memory de AgentCore); `src/adapters/agentcore/` | El grafo corre en prod gestionada sin cambiar contratos (ADR 0004) |
| 11 | **AgentCore Gateway + Policy** | Tools del legacy publicadas con Policy default-deny | Ninguna tool opera fuera de su tenant ni sin autorización |
| 12 | **AgentCore Identity + Policy** | Identidad entrante/saliente; credenciales fuera del código | Rotación de credenciales sin redeploy (ADR 0004: Identity+Policy van juntos) |
| 13 | **Observabilidad + seguridad** | CloudWatch con `tenant_id`/`correlation_id`, alarmas, Guardrails (grounding, temas denegados), runbooks, threat model a código | Dashboard por tenant; bloqueo de Guardrails verificado; runbooks creados |
| 14 | **Evaluación + optimización de costos** | `tests/agent_evals/` con datasets, presupuesto por conversación, revisión de precios | Evals obligatorias en verde en CI; `TODO(verify pricing)` cerrados |

## 2. Reglas que la ruta respeta (y que verifican los tests)

1. **Abstracción de modelo**: `LangGraph → LLMPort → BedrockLLM (Converse) → modelId`.
   Un solo punto de configuración (`BEDROCK_MODEL_ID`); cero `Claude(...)` disperso.
2. **Puertos primero**: LangGraph y el dominio no saben que existen DynamoDB, Aurora ni
   Bedrock; solo conocen `Protocol` (Paso 1) y los adapters llegan después.
3. **El LLM decide qué tool; LangGraph decide si puede usarla** (allowlist por tenant);
   **la tool ejecuta la operación real**. La disponibilidad no la inventa el modelo.
4. **Fakes hasta la infraestructura** (Pasos 3–5): repositorios en memoria; los adapters
   reales (legacy, Aurora, DynamoDB) se conectan en los Pasos 6–7 sin cambiar el dominio.
5. LangGraph solo en `application/` y `handler/` de cada slice; `domain/` sigue prohibido
   de ver `boto3`, `langgraph` o HTTP (import-linter en CI).

## 3. Mapa: fases históricas (1–9) → pasos de esta ruta

| Fase histórica | Pasos nuevos | Notas |
|---|---|---|
| 1 (esqueleto, docs, CI) | completada (previa) | Se conserva como referencia histórica |
| 2 (kernel `shared`) | completada (previa) | Idem |
| 3 (Terraform base) | **6** | |
| 4 (gateway, supervisor, customer_context) | gateway → **9**; supervisor y customer_context → **4** | |
| 5 (tenant_prompts, knowledge_rag, guardrails) | knowledge_rag → **7**; guardrails → **13**; tenant_prompts → **fuera de la ruta** | Hasta entonces los prompts viven en `prompts/` locales |
| 6 (appointments, orders, endpoints legacy) | appointments → **3** (grafo) y **5** (tools); orders → **5** | |
| 7 (sentiment, abuse, media, retention) | **fuera de la ruta** | `TODO(decision)`: se decidirá su momento tras el Paso 14 |
| 8 (AgentCore Runtime/Memory/Gateway/Identity) | Runtime → **10**; Gateway+Policy → **11**; Identity+Policy → **12** | Orden fijado por ADR 0004 |
| 9 (observabilidad, evals, CI/CD) | observabilidad → **13**; evals y costos → **14** | |

## 4. Fuera de la ruta actual (`TODO(decision)`)

| Slice | Motivo | Se decide |
|---|---|---|
| `tenant_prompts` | Los prompts se usan desde `prompts/` locales mientras no hay Prompt Management | Antes del Paso 13 si hace falta versionado por tenant |
| `sentiment_handoff` | No bloquea el agente de citas ni el RAG | Tras el Paso 14 |
| `abuse_protection` | Sin tráfico real de WhatsApp hasta el Paso 9 | Tras el Paso 14 |
| `media_handling` | El grafo de citas trabaja solo con texto al inicio | Tras el Paso 14 |
| `retention_archiving` | Cierra el ADR 0007 con casos de uso reales | Tras el Paso 14 |

## 5. Convenciones de esta ruta

- Cada paso actualiza el `AGENTS.md` de los slices que toca y deja la batería en verde
  (`ruff`, `ruff format`, `mypy`, `pytest`, `lint-imports`, `terraform fmt`).
- Un paso se da por cerrado solo con su criterio de «Hecho cuando…» de la tabla §1.
- Los cambios estructurales nuevos generan ADR; los precios quedan en
  `TODO(verify pricing)` hasta el Paso 14.
