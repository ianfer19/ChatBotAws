# CONTRIBUTING — cómo contribuir a ChatBotAws

Guía para humanos. Las IAs deben seguir [AGENTS.md](AGENTS.md); este documento complementa
con el flujo de trabajo del equipo.

## Flujo

1. **Issue/tarea** con alcance claro (qué slice, qué regla de negocio, qué paso).
2. **Rama** desde `master`: `feat/<slice>-<descripcion>` o `fix/<slice>-<descripcion>`.
3. **Implementación** siguiendo el orden `domain → application → infrastructure → handler`
   y las reglas de dependencia de AGENTS.md §3.
4. **Calidad local** antes de abrir PR:

   ```powershell
   ruff check src tests; ruff format src tests
   mypy
   pytest
   lint-imports
   terraform fmt -check -recursive infra
   ```

   O en un paso: `make verify` (Linux/macOS).

5. **Pre-commit** (opcional pero recomendado): `pre-commit install` y luego
   `pre-commit run --all-files`.
6. **Pull request** con: descripción del cambio, evidencia de CI verde, actualización del
   `AGENTS.md` del slice afectado, ADR nuevo si la decisión cambia estructura, datos,
   seguridad o costo.

## Commits

- Mensaje en **español**, formato convencional:
  - `feat(supervisor): añade intención greeting con ruta propia`
  - `fix(gateway): valida firma del webhook Meta antes de encolar`
  - `docs(adr): registra decisión 0007 de retención como pendiente`
  - `test(customer_context): cubre ventana de historial y resumen`
  - `chore(ci): añade lint-imports al pipeline`
- Un objetivo por commit; sin archivos ajenos al cambio.

## Definición de "terminado"

La checklist completa está en [AGENTS.md §9](AGENTS.md). Resumen: tipado + docstrings,
tests (unit/contract/eval según corresponda), CI verde completo, `AGENTS.md` del slice
actualizado, ADR si hay decisión estructural, cero secretos y TODOs explícitos.

## Qué se revisa en el PR

- Ningún import prohibido (CI lo verifica con import-linter y `test_repo_contract.py`).
- Ninguna regla de negocio solo en un prompt (debe existir en `domain/`).
- Ningún `tenant_id` proveniente del payload del LLM.
- Ninguna API de AWS inventada (`TODO(verify)` donde falte comprobar).
- Ningún dato real de clientes en tests o datasets (solo sintéticos).

## Dudas y decisiones

- Duda técnica sobre AWS → marca `TODO(verify)` y pregunta.
- Decisión estructural abierta → `TODO(decision)` + ADR con estado Pendiente.
- Incidente operativo → ver [docs/runbooks/README.md](docs/runbooks/README.md).
