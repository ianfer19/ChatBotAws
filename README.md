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

**Pasos 1–8 completados y Paso 9 en curso** (código y documentación listos; falta la
prueba con tráfico real en dev). Además, la **Fase A de la consola local** ya está
implementada: chat simulado, perfil de comercio y prompts editables sin AWS.

- **[docs/ROADMAP.md](docs/ROADMAP.md)** — ruta activa de 14 pasos y estado.
- **[AGENTS.md](AGENTS.md)** — fuente única de verdad para cualquier IA que trabaje aquí.
- **[docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)** — visión general.
- **[docs/architecture/CONSOLE.md](docs/architecture/CONSOLE.md)** — consola local.
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
web/      consola local (Astro + islas de React, Fase A)
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

## Consola local (Fase A)

Interfaz para conversar con el agente y editar por comercio el nombre, los bots y los
prompts, sin desplegar nada. Usa el mismo grafo que el REPL y, por defecto, un simulador
si no hay credenciales de AWS.

```powershell
# Terminal 1: API
python -m uvicorn handlers.console_api:app --app-dir src --reload --port 8000

# Terminal 2: interfaz
cd web
npm install
npm run dev
```

Abre `http://localhost:5173`. Guía completa: [docs/architecture/CONSOLE.md](docs/architecture/CONSOLE.md).

## Convenciones

Documentación y commits en **español**; identificadores de código en **inglés**. Reglas
completas, lista de "qué nunca hacer" y guías para agregar slices/tools/agentes:
[AGENTS.md](AGENTS.md). Flujo de contribución: [CONTRIBUTING.md](CONTRIBUTING.md).
