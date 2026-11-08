# Consola local de operación (Fase A)

Interfaz web para **hablar con el chatbot** y **editar su configuración por comercio**
sin desplegar nada. Es una herramienta interna de desarrollo y soporte: no sustituye al
webhook de Meta ni al consumer de producción.

## Qué permite

| Módulo | Capacidad |
|---|---|
| Chat | Enviar mensajes como cliente, ver la respuesta y reiniciar la sesión |
| Traza | Intención, confianza, destino, error de ruta, draft resuelto, latencia y hilo |
| Comercio | Nombre visible, tono, idioma, `model_id` y bots activos |
| Prompts | Editar `supervisor`, `appointments`, `orders` y `faq`; restaurar la base |
| Estado | Contadores de citas y pedidos en memoria del comercio |

La traza y el chat usan **el mismo grafo** que `scripts/chat_citas.py`: supervisor,
citas, pedidos, FAQ, contexto de cliente y checkpointer en memoria.

## Qué NO es (Fase A)

- No pasa por Meta, SQS ni API Gateway.
- No usa Bedrock Prompt Management, DynamoDB, Cognito ni Terraform.
- No integra un POS/legacy real: usa catálogo, horarios y conocimiento sintéticos.
- No guarda historial de chat entre reinicios (la configuración sí persiste).
- No tiene autenticación: escucha en `127.0.0.1` y nunca debe exponerse a Internet.

## Cómo arrancarla

Dos terminales, desde la raíz del repo.

**1. API (FastAPI):**

```powershell
pip install -e ".[dev]"
$env:CHATBOT_CONSOLE_LLM = "fake"   # opcional: auto | fake | bedrock
python -m uvicorn handlers.console_api:app --app-dir src --reload --port 8000
```

**2. Interfaz (Astro + React):**

```powershell
cd web
npm install
npm run dev
```

Abre `http://localhost:5173`. Astro usa Vite por dentro y hace proxy de `/api` a
`http://127.0.0.1:8000`.

## Modos de LLM

| Modo | Comportamiento |
|---|---|
| `auto` (por defecto) | Usa Bedrock si hay `CHATBOT_BEDROCK_MODEL_ID` y credenciales; si no, simulador |
| `fake` | Simulador determinista, sin AWS; las respuestas no reflejan el prompt |
| `bedrock` | Fuerza el modelo real; si falta configuración, cae al simulador con aviso |

Variables relevantes:

- `CHATBOT_BEDROCK_MODEL_ID` y credenciales de AWS para el modo real.
- `CHATBOT_CONSOLE_LLM` para forzar el motor.
- `CHATBOT_CONSOLE_DATA_DIR` (por defecto `console-data/`).
- `CHATBOT_CONSOLE_CORS_ORIGINS` (por defecto los dos orígenes de Vite/Astro).

## Datos locales

`console-data/tenants.json` guarda el perfil y los overrides de prompt. Está ignorado
por git; `console-data/tenants.example.json` documenta el esquema. No contiene secretos:
las credenciales de canal/POS vivirán en SSM en las fases de producción.

## API

```text
GET    /api/health
GET    /api/tenants
GET    /api/tenants/{tenant_id}
PUT    /api/tenants/{tenant_id}
GET    /api/tenants/{tenant_id}/prompts
GET    /api/tenants/{tenant_id}/prompts/{kind}
PUT    /api/tenants/{tenant_id}/prompts/{kind}
DELETE /api/tenants/{tenant_id}/prompts/{kind}
GET    /api/tenants/{tenant_id}/state
POST   /api/chat
POST   /api/chat/reset
```

`kind` es uno de `supervisor`, `appointments`, `orders`, `faq`.

## Cómo se aplica un cambio

1. La API guarda el perfil o el prompt en `console-data/tenants.json`.
2. En el siguiente turno, `ConsoleRuntime.get()` detecta que el perfil cambió.
3. Recompila el grafo del comercio **conservando** sus stores en memoria (citas,
   pedidos, drafts y checkpointer).
4. El prompt override llega al `system` del nodo correspondiente; si no hay override,
   se usa `prompts/base/<kind>.md`.

## Arquitectura

```text
Astro (web/) ──proxy /api──▶ FastAPI (src/handlers/console_api.py)
                                      │
                                      ▼
                         ConsoleRuntime (un grafo por comercio)
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
   supervisor                  appointments/orders                 faq
        │                             │                             │
        └──────────── stores en memoria + FakeLLM o BedrockLLM ─────┘
                                      │
                                      ▼
                         console-data/tenants.json
```

El composition root vive en `src/handlers/` (ADR 0014). El slice `tenant_prompts`
aporta el perfil y los casos de uso; los grafos solo reciben un `system_prompt`
opcional y un `tenant_name` opcional.

## Pruebas

```powershell
python -m pytest -q tests/unit/test_console_*.py
python -m ruff check src tests
python -m mypy
python -m lint-imports
cd web; npm run check; npm run build
```

## Siguiente fase

La Fase B sustituye el repositorio JSON por **Bedrock Prompt Management** (contenido y
versiones) y DynamoDB (pin de versión activa). La Fase C conecta el POS/legacy real y la
Fase D despliega la consola con autenticación.
