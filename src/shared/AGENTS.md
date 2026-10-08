# AGENTS.md — `shared/` (kernel)

> Reglas generales del repo: [AGENTS.md](../../AGENTS.md) raíz. Este archivo solo cubre
> el kernel.

## Responsabilidad

Piezas **transversales y puras** usadas por todos los slices y por `adapters/`: errores
tipados, logging estructurado, configuración, contexto de tenant/correlación, contratos
entre slices y ports compartidos. El kernel **no contiene lógica de negocio ni adapters
AWS** y **nunca importa** `slices.*` ni `adapters.*` (lo verifica import-linter en CI).

## Qué va aquí (y qué no)

| Paquete | Va | No va |
|---|---|---|
| `errors/` | Excepciones tipadas con código estable (ToolError, TenantError, ValidationError...) | Strings de mensajes de UI; reglas de negocio |
| `logging/` | Formatter JSON, `correlation_id` y `tenant_id` en cada evento, contexto de request | PII completa, tokens, credenciales |
| `config/` | Pydantic Settings desde variables de entorno | Valores por defecto sensibles, secretos en código |
| `context/` | `contextvar` de tenant/correlación, helper de composición (DI) | Estado global mutable |
| `contracts/` | Modelos Pydantic de mensajes/eventos entre slices (versionados) | Implementaciones, lógica de caso de uso |
| `ports/` | `LLMPort`, `VectorStorePort`, `MemoryStorePort`, `ClockPort`, `EventBusPort` (Protocol) | Adapters concretos (viven en `adapters/`) |

## Estado (Fase 2: implementado)

| Paquete | Módulos | Tests |
|---|---|---|
| `errors/` | `base.py`: `AppError` (+ `code`/`http_status`), `ValidationError`, `TenantError`, `TenantNotFoundError`, `ContextNotSetError`, `ToolError`, `ToolTimeoutError` | `tests/unit/test_shared_errors.py` |
| `context/` | `tenant.py`: `TenantContext` (frozen) + `set_context`/`reset_context`/`get_context`/`current_context`/`bind_context` | `tests/unit/test_shared_context.py` |
| `config/` | `settings.py`: `Settings` (`CHATBOT_ENVIRONMENT`, `CHATBOT_LOG_LEVEL`, `CHATBOT_BEDROCK_MODEL_ID` obligatorio, `CHATBOT_BEDROCK_TIMEOUT_SECONDS`) + `load_settings` | `tests/unit/test_shared_config.py` |
| `logging/` | `formatter.py` (JSON + redacción de secretos) + `logger.py` (`configure_logging`, `get_logger`) | `tests/unit/test_shared_logging.py` |
| `contracts/` | `types.py` (`Channel`, `Intent`, `AgentName`) + `messages.py` (`InboundMessage`, `OutboundMessage`, `RoutedTurn`, `CustomerContext`; `schema_version`, `frozen`, `extra=forbid`) | `tests/unit/test_shared_contracts.py` |
| `ports/` | `base.py`: `ClockPort`, `EventBusPort`; `llm.py`: `LLMMessage`, `LLMResult`, `LLMPort`; `vector.py`: `VectorRecord`, `VectorHit`, `VectorStorePort`; `memory.py`: `MemoryStorePort` (todos `runtime_checkable`) | `tests/unit/test_shared_ports.py` |

Errores propios de un slice: subclasificar `AppError` en el slice (p. ej.
`InvalidSignatureError` en `conversation_gateway`). Contratos nuevos: añadir el modelo a
`messages.py` (o `types.py`), test de round-trip y registro aquí.

## Convenciones

- Todo lo público con docstring en español (qué/por qué/Args/Returns/Raises).
- Modelos Pydantic v2, firmas anotadas, sin `Any` implícito (mypy estricto).
- Los contratos entre slices se versionan: añadir campos es compatible; romper un contrato
  exige migrar a todos los emisores/receptores en el mismo PR.
- Errores: los adapters los traducen; los handlers traducen errores a respuestas HTTP;
  jamás se expone un stack trace al usuario final.

## Cómo añadir algo

1. **Error nuevo**: clase en `errors/` con código y mensaje en español + test unit que
   cubra su traducción a respuesta.
2. **Contrato nuevo**: modelo Pydantic en `contracts/` con docstring, test de serialización
   (round-trip) y registro en el `AGENTS.md` del slice emisor y del receptor.
3. **Port nuevo**: Protocol en `ports/` con typing completo; la implementación concreta va
   en `adapters/` (o en el `infrastructure/` del slice si es específica).

## Cómo probarlo

`pytest tests/unit` — el kernel es puro, así que sus tests son rápidos y no necesitan AWS.
