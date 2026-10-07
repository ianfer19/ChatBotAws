# CLAUDE.md — guía para Claude/opencode

**Lee primero [AGENTS.md](AGENTS.md): es la fuente única de verdad** (propósito del sistema,
mapa del repo, regla de dependencias, qué nunca hacer, cómo agregar slices/tools/agentes,
definición de "terminado", glosario). Este archivo solo añade lo específico de la herramienta.

## Comandos

```powershell
# Windows (PowerShell) — ejecutar antes de dar por terminado cualquier cambio
ruff check src tests              # lint
ruff format src tests             # formato (auto-fix)
mypy                              # tipos
pytest                            # tests (incluye tests/unit/test_repo_contract.py)
lint-imports                      # reglas de dependencia entre capas
terraform fmt -check -recursive infra
```

Equivalente en un solo paso (Linux/macOS): `make verify && make tf-fmt`.

## Orden de trabajo recomendado

1. `domain/` del slice → 2. `application/` → 3. `infrastructure/` (adapters) → 4. `handler/`.
5. Tests: unit del dominio primero, luego contract, luego evals de agente si cambia
   comportamiento conversacional.
6. Actualizar el `AGENTS.md` del slice tocado.
7. Ejecutar la batería completa de comandos anteriores.

## Reglas duras (resumen; el detalle está en AGENTS.md §5)

- Docstrings en español en toda función/clase pública; código e identificadores en inglés.
- `domain/` puro: ni `boto3`, ni `langgraph`, ni HTTP, ni imports de otros slices.
- Los slices solo se comunican por `shared/contracts/`.
- `tenant_id` NUNCA sale del payload del LLM: viene del contexto (`shared/context/`).
- Nada de secretos; dudas sobre APIs de AWS → `TODO(verify)`, precios → `TODO(verify pricing)`.
- Sin emojis en el código ni en los docs.
- Commits en español, formato convencional (ver CONTRIBUTING.md).

## Contexto del proyecto

- Fase actual: **1 (esqueleto y documentación)** — ver tabla de fases en AGENTS.md §10.
- Backend legacy: `C:\Users\ianfe\OneDrive\Documentos\GitHub\sahagunonline\back`
  (solo lectura de referencia: su `AGENTS.md`, `docs/catalogo_endpoints.md` y
  `docs/Architecture.md` explican el sistema actual y el contrato de APIs/tools).
- Decisiones ya cerradas: ADR 0001–0009 en `docs/adr/`; retención (0007) pendiente hasta Fase 7.
