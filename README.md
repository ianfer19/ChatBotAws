# ChatBotAws

Plataforma **SaaS multi-comercio** que opera chatbots de WhatsApp, Instagram y Messenger
sobre AWS para los comercios de Sahagún Online (Colombia): restaurantes, hoteles, clínicas y
gimnasios.

- **Orquestación**: LangGraph sobre Amazon Bedrock (modelos tras un port intercambiable).
- **Conocimiento**: Aurora PostgreSQL Serverless v2 + pgvector (RAG con grounding).
- **Operación**: DynamoDB (contexto, conversaciones recientes, límites de abuso) y S3 (archivo).
- **Producción**: Bedrock AgentCore (Runtime, Memory, Gateway, Identity, Policy) con adopción modular.
- **Negocio**: acciones vía tools validadas contra el backend legacy (`sahagunonline/back`).
- **Infraestructura**: Terraform, módulos reutilizables, entornos dev/staging/prod.

## Estado

**Fases 1–2 completadas — esqueleto, documentación y kernel `shared`.** Aún no hay
lógica de negocio. El sistema, su ruta ([docs/ROADMAP.md](docs/ROADMAP.md)) y sus
decisiones están documentados para humanos e IAs:

- **[AGENTS.md](AGENTS.md)** — fuente única de verdad para cualquier IA que trabaje aquí.
- **[docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)** — visión general.
- **[docs/adr/README.md](docs/adr/README.md)** — decisiones arquitectónicas ya tomadas.

## Estructura

```
docs/     arquitectura, ADRs, IA (prompts/RAG/guardrails/evals), seguridad, runbooks
src/
  shared/     kernel: errores, logging, config, contexto de tenant, contracts, ports
  adapters/   adapters transversales (bedrock, dynamodb, aurora, s3, comprehend, agentcore, legacy)
  slices/     11 slices verticales (domain/application/infrastructure/handler)
infra/    módulos Terraform + envs dev/staging/prod
prompts/  espejo local de Bedrock Prompt Management (base/ y tenants/)
tests/    unit, integration, contract, agent_evals
```

## Puesta en marcha

```powershell
# Windows (PowerShell)
pip install -e ".[dev]"
ruff check src tests
mypy
pytest
lint-imports
```

```bash
# Linux/macOS
make install && make verify
```

## Convenciones

Documentación y commits en **español**; identificadores de código en **inglés**. Reglas
completas, lista de "qué nunca hacer" y guías para agregar slices/tools/agentes:
[AGENTS.md](AGENTS.md). Flujo de contribución: [CONTRIBUTING.md](CONTRIBUTING.md).
