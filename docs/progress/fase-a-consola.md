# Fase A — consola local de operación

> Herramienta de desarrollo fuera de la ruta de 14 pasos. Estado: **implementada**.

## Alcance

- [x] Frontend Astro + islas de React en `web/`.
- [x] API FastAPI en `src/handlers/console_api.py`.
- [x] Slice `tenant_prompts` con perfil y overrides en JSON local.
- [x] Runtime por comercio con stores en memoria y checkpointer.
- [x] Chat simulado con traza (intención, destino, latencia, hilo).
- [x] Edición de `supervisor`, `appointments`, `orders` y `faq`.
- [x] Restauración a la plantilla base.
- [x] Nombre comercial, tono, idioma, modelo y `allowed_bots`.
- [x] LLM `auto` (Bedrock si hay credenciales; simulador si no) con aviso.
- [x] Tests de configuración, fake LLM, runtime y API.
- [x] CI del frontend (`npm run check` + `npm run build`).

## Fuera de la Fase A

- [ ] Bedrock Prompt Management y versionado/rollback (Fase B).
- [ ] DynamoDB para perfiles y pins (Fase B).
- [ ] POS/legacy real y catálogo/horarios reales (Fase C).
- [ ] Cognito, API Gateway, S3/CloudFront y Terraform (Fase D).
- [ ] Evals obligatorias antes de activar un prompt (Fase E).
- [ ] Visor de conversaciones persistidas y auditoría en la UI (Fase E).

## Verificación

```powershell
python -m pytest -q tests/unit/test_console_*.py
python -m ruff check src tests scripts
python -m mypy
python -m lint-imports
cd web; npm run check; npm run build
```
