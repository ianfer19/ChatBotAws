# AGENTS.md — ChatBotAws

> **Fuente única de verdad** para cualquier IA o desarrollador que abra este repositorio.
> Guías específicas de herramientas: [CLAUDE.md](CLAUDE.md). Convenciones de contribución: [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 1. Propósito del sistema

Plataforma **SaaS multi-comercio (multi-tenant)** que opera chatbots de WhatsApp, Instagram y
Messenger para los comercios de Sahagún Online (restaurantes, hoteles, clínicas, gimnasios en
Colombia). El sistema:

- Recibe mensajes desde las APIs de Meta (webhook con verificación y firma).
- Decide la intención (saludo, ventas, citas, pedidos, FAQ) con un supervisor.
- Orquesta con **LangGraph** sobre **Amazon Bedrock** (modelos tras un port intercambiable).
- Responde **solo con conocimiento fundamentado** (RAG sobre Aurora+pgvector) y ejecuta acciones
  **solo vía tools validadas** contra el backend legacy (`sahagunonline/back`).
- Protege el sistema con Guardrails, detección de abuso y handoff humano.

**Estado: Fases 1 y 2 completadas** (esqueleto, documentación, CI y kernel `shared`) y
**Pasos 1-7 de la ruta** (ports, Bedrock, grafo de citas, supervisor + contexto, tools
con lógica de negocio propose/commit, infraestructura Terraform base, y RAG +
Aurora/pgvector con grafo `faq`). La ruta activa es [docs/ROADMAP.md](docs/ROADMAP.md)
(14 pasos); visión general: [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) y §10.

---

## 2. Mapa del repositorio

```
.
├── AGENTS.md                  # Este archivo (reglas universales)
├── CLAUDE.md                  # Comandos y convenciones para Claude/opencode
├── CONTRIBUTING.md            # Flujo de trabajo para humanos
├── README.md                  # Visión de entrada
├── Makefile                   # Atajos (en Windows ver §5)
├── pyproject.toml             # ruff + mypy + pytest + import-linter (config única)
├── .pre-commit-config.yaml    # Hooks locales de calidad
│
├── docs/
│   ├── architecture/          # Cómo está construido el sistema
│   │   ├── OVERVIEW.md                # Visión general y requisitos
│   │   ├── HEXAGONAL_AND_SLICING.md   # Arquitectura y reglas de dependencia
│   │   ├── DATA_MODEL.md              # Qué va en Aurora / DynamoDB / S3 y por qué
│   │   ├── MULTI_TENANCY.md           # Resolución y filtrado de tenant
│   │   ├── AGENTCORE.md               # Qué va en AgentCore vs Lambda
│   │   ├── INTEGRATION_WITH_LEGACY.md # Contrato con sahagunonline/back
│   │   └── diagrams/                  # Fuentes Mermaid
│   ├── adr/                   # Architecture Decision Records (0001..0009)
│   ├── ai/                    # Prompts, guardrails, RAG, memoria, evals
│   ├── security/              # Threat model, retención de datos
│   ├── progress/              # Checklist vivo del paso en curso (Paso 6)
│   └── runbooks/              # Procedimientos operativos (índice)
│
├── src/
│   ├── shared/                # Kernel: errors, logging, config, context, contracts, ports
│   ├── adapters/              # Adapters AWS transversales (bedrock, dynamodb, aurora, s3,
│   │                          #   comprehend, agentcore, legacy_backend)
│   └── slices/                # UNA carpeta por funcionalidad (vertical slicing)
│       └── <slice>/           #   domain/ application/ infrastructure/ handler/ + AGENTS.md
│
├── infra/
│   ├── modules/               # Módulos Terraform reutilizables (state, network, aurora,
│   │                          #   dynamodb, s3, kms, lambda, apigw, bedrock, agentcore, iam, observability)
│   ├── bootstrap/             # Estado de Terraform (backend local; apply único a mano)
│   └── envs/{dev,staging,prod}/
│
├── prompts/                   # Espejo local de Bedrock Prompt Management
│   ├── base/                  #   plantillas canónicas compartidas
│   └── tenants/<tenant_id>/   #   personalización por comercio (usar _example/)
│
├── tests/
│   ├── unit/                  # Unidades + test de estructura del repo
│   ├── integration/           # Contra servicios reales/localstack
│   ├── contract/              # Contratos entre slices y con el legacy
│   └── agent_evals/           # Datasets y evaluaciones del agente
│
├── scripts/                   # Utilidades de desarrollo (chat_citas.py: REPL del grafo)
│
└── .github/workflows/         # CI: quality (lint/tipos/tests/dependencias) + terraform
```

**Slices (11)**: `conversation_gateway`, `supervisor`, `appointments`, `orders`,
`knowledge_rag`, `customer_context`, `tenant_prompts`, `sentiment_handoff`,
`abuse_protection`, `media_handling`, `retention_archiving`.
Cada slice tiene su propio `AGENTS.md` con responsabilidad, ports, tablas, tools y tests.

---

## 3. Regla de dependencia (obligatoria, verificada en CI)

```
handler  →  application  →  domain
infrastructure  →  domain
domain  →  (stdlib + pydantic + shared; NADA más)
shared y adapters  →  NUNCA importan slices
los slices NO se importan entre sí  →  se comunican solo vía shared/contracts
```

| Verificación | Herramienta | Dónde |
|---|---|---|
| Dirección de dependencias entre capas | `import-linter` | `pyproject.toml` → `[tool.importlinter]` |
| Aislamiento entre slices + pureza del domain (AST) | `pytest` | `tests/unit/test_repo_contract.py` |
| Ambos corren en CI | GitHub Actions | `.github/workflows/ci.yml` |

Razón: el dominio es lo único estable; si importa AWS, framework o un slice vecino, la
arquitectura se degrada silenciosamente. Detalle y justificación:
[docs/architecture/HEXAGONAL_AND_SLICING.md](docs/architecture/HEXAGONAL_AND_SLICING.md).

---

## 4. Convenciones de código

- **Idioma**: documentación, comentarios, mensajes de error y commits en **español**;
  nombres de archivos, carpetas, funciones, clases, variables y logs en **inglés**.
- **Python 3.12**, tipado completo (`mypy` estricto), modelos con **Pydantic v2**.
- **Docstring obligatorio** en toda función y clase pública: qué hace, por qué existe,
  parámetros, retorno, errores y un ejemplo breve si el uso no es obvio.
  En español. Formato: triple comilla con descripción + Args/Returns/Raises.
- **Comentarios**: explican el *por qué*, nunca el *qué*. Si el código necesita explicar qué
  hace, refactoriza el código.
- **Sin** secretos hardcodeados, sin variables globales mutables, sin funciones de más de
  ~50 líneas, sin `except:` ciego.
- **Tipos**: firmas anotadas siempre; modelos de dominio en `domain/entities.py` (o
  equivalente) con Pydantic; los contratos entre slices en `shared/contracts/`.
- **Errores**: excepciones tipadas en `shared/errors/`; los handlers las traducen a
  respuestas; nunca se filtra un stack trace al usuario final.
- **Logging**: siempre el logger estructurado de `shared/logging/`; cada evento lleva
  `correlation_id` y `tenant_id`. Nunca loguear PII completa ni tokens.
- **Config**: `shared/config/` con Pydantic Settings desde variables de entorno; jamás
  valores sensibles en el repo.
- **TODO**: ante cualquier duda sobre una API de AWS se marca `TODO(verify)`;
  decisiones abiertas marcan `TODO(decision)`; precios marcan `TODO(verify pricing)`.
  **Nunca inventes nombres de API, parámetros o límites de AWS.**

### Comandos

```powershell
# Windows (PowerShell) — mismos pasos que el Makefile de CI
pip install -e ".[dev]"          # instalar herramientas de desarrollo
ruff check src tests scripts       # lint
ruff format --check src tests scripts  # formato
mypy                             # tipos
pytest                           # tests
lint-imports                     # regla de dependencia
terraform fmt -check -recursive infra
```

```bash
# Linux/macOS/CI
make install && make verify      # lint + tipos + tests + dependencias
make tf-fmt                      # formato Terraform
```

---

## 5. Qué NUNCA hacer (lista explícita)

1. **Nunca** dejar que el LLM lea o escriba directamente en una base de datos: solo tools
   con schema, validación, autorización por tenant, timeout, idempotencia y logs.
2. **Nunca** usar el LLM como fuente de verdad de precios, stock, disponibilidad, estado de
   pedido ni horas. Esos datos vienen de tools/backend o del dominio.
3. **Nunca** poner reglas de negocio en prompts. Viven en `domain/`.
4. **Nunca** confiar en el `tenant_id` que llega en el payload del LLM o del usuario:
   siempre sale del contexto resuelto en el gateway (`shared/context/`).
5. **Nunca** importar entre slices (p. ej. `orders` importando `supervisor`). Comunícate por
   `shared/contracts/`.
6. **Nunca** importar `boto3`, clientes AWS, `langgraph` o HTTP desde `domain/`.
7. **Nunca** hardcodear secretos, access tokens de Meta ni credenciales: Secrets Manager/SSM.
8. **Nunca** inventar APIs de AWS: si no estás seguro, `TODO(verify)` y pregunta.
9. **Nunca** implementar un cambio sin actualizar el `AGENTS.md` del slice afectado, ni
   merger sin CI verde (lint, tipos, tests, dependencias, terraform).
10. **Nunca** romper la defensa en profundidad de la hora del pedido (ver §7): la tool no
    existe, el dominio rechaza, Policy deniega, Guardrails bloquea, test de regresión.
11. **Nunca** modificar prompts de `prompts/base/` sin pasar por los evals
    ([docs/ai/EVALUATION.md](docs/ai/EVALUATION.md)) y dejar nota en el changelog del prompt.
12. **Nunca** subir datos reales de clientes (números, nombres, transcripciones) al repo:
    los datasets de tests son sintéticos.

---

## 6. Cómo agregar… (paso a paso)

### 6.1 Un slice nuevo

1. Crea `src/slices/<nuevo_slice>/` con `domain/`, `application/`, `infrastructure/`,
   `handler/` y un `AGENTS.md` (usa la plantilla de contenido de
   [src/slices/AGENTS.md](src/slices/AGENTS.md)).
2. Cada paquete lleva `__init__.py` **con docstring de responsabilidad** (el test de
   estructura lo exige).
3. Implementa primero `domain/` (entidades, reglas, ports como `Protocol`/`ABC`), luego
   `application/` (casos de uso), después `infrastructure/` (adapters) y al final
   `handler/` (entrada + composición de dependencias).
4. Si se comunica con otros slices, define los mensajes en `shared/contracts/` (Pydantic).
5. Ejecuta `pytest tests/unit/test_repo_contract.py`, `lint-imports`, `mypy` y `ruff`.
6. Registra el slice en la tabla de §2 y en `src/slices/AGENTS.md`.
7. Si consume recursos AWS, añade el módulo/recurso en `infra/` siguiendo
   [infra/README.md](infra/README.md) y las tags de costo por tenant/entorno.

### 6.2 Una tool nueva para el LLM

1. **Regla primero**: escribe la regla de negocio en `domain/` del slice (nada de esto va
   en el prompt).
2. Define el esquema de entrada/salida con Pydantic en `application/` (tipos estrictos;
   el `tenant_id` **no** es parámetro de la tool: se inyecta del contexto).
3. Implementa la llamada en `infrastructure/` (o `adapters/` si es transversal) con:
   validación, autorización por tenant, **timeout**, idempotencia y log de auditoría con
   `correlation_id`.
4. Registra la tool en el agente correspondiente (LangGraph tool node; en el Paso 11, además
   como target del **AgentCore Gateway** con su **Policy** de autorización, default-deny).
5. Añade `allowed_bots`/allowlist por tenant si aplica (ver
   [docs/architecture/MULTI_TENANCY.md](docs/architecture/MULTI_TENANCY.md)).
6. Tests: unit de dominio + contract del esquema + caso en `tests/agent_evals/datasets/`
   (incluye un caso negativo: la tool no puede operar sobre otro tenant).
7. Documenta la tool en el `AGENTS.md` del slice (sección "Tools expuestas al LLM").

### 6.3 Un agente nuevo (nodo especialista de LangGraph)

1. Define la responsabilidad del agente y su intención de entrada en `supervisor/`
   (conditional edge nuevo; el saludo/smalltalk SIEMPRE tiene ruta propia).
2. Crea o extiende el slice que lo aloja con su grafo en `application/`
   (state, nodes, conditional edges, checkpointer).
3. Prompts: plantilla base en `prompts/base/`, personalización por tenant en
   `prompts/tenants/<tenant_id>/`, publicación en Bedrock Prompt Management
   (ver [docs/ai/PROMPT_MANAGEMENT.md](docs/ai/PROMPT_MANAGEMENT.md)).
4. Allowlist de tools mínima necesaria (principio de mínimo privilegio).
5. Guardrails aplicables (temas denegados, grounding si responde con RAG).
6. Eval obligatoria en `tests/agent_evals/datasets/` antes de aceptar el cambio.
7. Actualiza el `AGENTS.md` del slice y, si hay nueva decisión estructural, crea un ADR.

---

## 7. Reglas de negocio críticas (defensa en profundidad)

**El chatbot NO puede modificar la hora de un pedido.** Cinco capas, ninguna suficiente
por sí sola:

1. La tool **no existe** en la allowlist del LLM.
2. El dominio `orders/domain` rechaza la operación (`Order` no expone ese cambio).
3. **AgentCore Policy** deniega la acción (default-deny, Paso 11).
4. **Bedrock Guardrails**: tema denegado configurado.
5. **Test de regresión** que falla si cualquiera de las capas anteriores se retira.

Mismo patrón para cualquier regla crítica: ninguna depende solo del prompt.

---

## 8. Decisiones arquitectónicas ya tomadas

| # | Decisión | ADR |
|---|---|---|
| D1 | Reemplazo gradual del backend legacy: webhook Meta propio, migración comercio por comercio | [0006](docs/adr/0006-reemplazo-gradual-del-backend-legacy.md) |
| D2 | Datos de negocio vía APIs del legacy expuestas con AgentCore Gateway + Policy; conocimiento en Aurora | [0002](docs/adr/0002-reparto-de-datos-aurora-dynamodb-s3.md) |
| D3 | Tres canales Meta tras un `ChannelPort` único | [0009](docs/adr/0009-channelport-unico-canales-meta.md) |
| D4 | LangGraph + Bedrock hoy; AgentCore con adopción modular (Runtime → Memory → Gateway → Identity+Policy) | [0004](docs/adr/0004-orquestacion-langgraph-agentcore-modular.md) |
| D5 | `tenant_id` = `store_id` legado, resuelto en el gateway y propagado en todo el contexto | [0003](docs/adr/0003-multi-tenancy-tenant-en-gateway.md) |
| D6 | Retención de conversaciones/media: **pendiente**, fuera de la ruta (ROADMAP §4) | [0007](docs/adr/0007-retencion-de-conversaciones-y-media.md) |
| D7 | Supervisor compone a los especialistas por invocación (nodo anidado tras un port) | [0010](docs/adr/0010-composicion-de-grafos-por-invocacion.md) |
| D8 | Confirmación por política de riesgo con drafts propose/commit (sin ritual fijo; sin depender del checkpointer) | [0011](docs/adr/0011-confirmacion-por-politica-con-drafts.md) |
| D9 | Infraestructura: estado remoto con bootstrap, un stack por entorno y Lambdas sin VPC por defecto | [0012](docs/adr/0012-infraestructura-terraform-estado-y-red.md) |

Requisitos de corrección que deben mantenerse siempre (con sus tests):
**saludo** → intención `greeting`/`smalltalk` con ruta propia y saludo neutral, sin enrutar
a ventas; **contexto** → todo turno incluye `get_customer_context` + historial con ventana
y resumen (hay un test que falla si el prompt llega sin ambos).

---

## 9. Definición de "terminado"

Un trabajo está terminado cuando:

- [ ] Código con tipado completo, docstrings (qué/por qué/params/retorno/errores) y sin
      duplicación obvia.
- [ ] Tests: unit del dominio + contract si toca contratos + eval si cambia comportamiento
      del agente.
- [ ] CI verde: `ruff` + `ruff format --check` + `mypy` + `pytest` + `lint-imports` +
      `terraform fmt -check`.
- [ ] `AGENTS.md` del slice afectado actualizado (o creado).
- [ ] ADR creado si la decisión cambia estructura, datos, seguridad o costo.
- [ ] Cero secretos; TODOs (`verify`/`decision`) explícitos para lo que no se pudo cerrar.
- [ ] Commit en español con mensaje convencional (ver [CONTRIBUTING.md](CONTRIBUTING.md)).

---

## 10. Ruta del proyecto (ROADMAP)

Ruta activa: **[docs/ROADMAP.md](docs/ROADMAP.md)** (14 pasos, criterios de hecho y mapa
de las fases históricas 1–9 a los pasos nuevos).

| Paso | Alcance | Estado |
|---|---|---|
| 1 | Arquitectura/base: ports (`LLMPort` Converse, `VectorStorePort`, `MemoryStorePort`, repositorios de citas/pedidos), dependencias `boto3`+`langgraph`, ROADMAP | **hecho** |
| 2 | Bedrock + abstracción de modelos (`adapters/bedrock`, Converse API) | **hecho** |
| 3 | LangGraph: grafo de citas + `AgentState` en `appointments/application` | **hecho** |
| 4 | Supervisor (routing, saludo) + `customer_context` (contexto obligatorio por turno) | **hecho** |
| 5 | Tools + lógica de negocio (citas, pedidos) con dobles en memoria | **hecho** |
| 6 | Infraestructura Terraform base (state, red, DynamoDB, S3, Aurora, IAM, apigw, lambda) | **hecho** |
| 7 | RAG + Aurora/pgvector (`knowledge_rag`, `VectorStorePort` → `adapters/aurora`) | **hecho** |
| 8 | Memory / checkpoints (checkpointer de LangGraph, ADR 0007) | pendiente |
| 9 | Conversation gateway (webhook Meta, 3 canales, firma y tenant) | pendiente |
| 10 | AgentCore Runtime (+ Memory de AgentCore) | pendiente |
| 11 | AgentCore Gateway + Policy | pendiente |
| 12 | AgentCore Identity + Policy | pendiente |
| 13 | Observabilidad + seguridad (CloudWatch, Guardrails, runbooks) | pendiente |
| 14 | Evaluación + optimización de costos (agent evals, pricing) | pendiente |

Fuera de la ruta (`TODO(decision)`): `tenant_prompts`, `sentiment_handoff`,
`abuse_protection`, `media_handling`, `retention_archiving` — ver ROADMAP §4.
Fases históricas ya completadas: 1 (esqueleto, docs, CI) y 2 (kernel `shared`).

---

## 11. Glosario

| Término | Definición |
|---|---|
| **tenant** | Un comercio cliente. Su identificador es el `store_id` legado (p. ej. `Sede_Elite_01`). Todo dato se filtra por él. |
| **slice** | Carpeta vertical con una funcionalidad completa (domain/application/infrastructure/handler). Unidad de organización y de aislamiento. |
| **port** | Interfaz (Protocol/ABC) que define QUÉ necesita el dominio; vive en `domain/` o `shared/ports/`. |
| **adapter** | Implementación concreta de un port (AWS, HTTP, canal); vive en `infrastructure/` o `adapters/`. |
| **grounding** | Respuesta del modelo anclada en fuentes recuperadas (RAG). Se verifica con el contextual grounding check de Guardrails. |
| **handoff** | Traspaso de la conversación a un humano (`human_takeover`) cuando sentimiento/reglas lo indican. |
| **correlation_id** | Identificador único por mensaje/conversación que atraviesa logs, tools y servicios. |
| **tool** | Función expuesta al LLM con esquema validado; única vía del modelo para actuar sobre datos. |
| **RAG** | Retrieval-Augmented Generation: la respuesta se construye con chunks recuperados de Aurora+pgvector. |
| **checkpointer** | Persistencia del state de LangGraph entre turnos (corto plazo; no es memoria de negocio). |
| **allowed_bots** | Entitlements por tenant: qué bots (ventas, citas, pedidos) tiene activados un comercio. |
| **AgentCore** | Suite de AWS para agentes en producción: Runtime, Memory, Gateway, Identity, Policy. Ejecuta LangGraph; no lo reemplaza. |
| **defensa en profundidad** | Regla crítica protegida en varias capas (tool, dominio, Policy, Guardrails, test), nunca solo en el prompt. |

---

## 12. Enlaces rápidos

- **Arquitectura**: [OVERVIEW](docs/architecture/OVERVIEW.md) ·
  [Hexagonal y slicing](docs/architecture/HEXAGONAL_AND_SLICING.md) ·
  [Modelo de datos](docs/architecture/DATA_MODEL.md) ·
  [Multi-tenancy](docs/architecture/MULTI_TENANCY.md) ·
  [AgentCore](docs/architecture/AGENTCORE.md) ·
  [Integración con legacy](docs/architecture/INTEGRATION_WITH_LEGACY.md)
- **ADRs**: [índice y plantilla](docs/adr/README.md)
- **IA**: [Prompt engineering](docs/ai/PROMPT_ENGINEERING.md) ·
  [Prompt management](docs/ai/PROMPT_MANAGEMENT.md) ·
  [Guardrails](docs/ai/GUARDRAILS.md) ·
  [RAG](docs/ai/RAG.md) ·
  [Memoria y contexto](docs/ai/MEMORY_AND_CONTEXT.md) ·
  [Evals](docs/ai/EVALUATION.md)
- **Seguridad**: [SECURITY](docs/security/SECURITY.md) ·
  [Threat model](docs/security/THREAT_MODEL.md) ·
  [Retención de datos](docs/security/DATA_RETENTION.md)
- **Operación**: [Runbooks](docs/runbooks/README.md) · [Infra](infra/README.md) ·
  [Tests de agente](tests/agent_evals/README.md)
