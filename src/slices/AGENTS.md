# AGENTS.md — `slices/` (índice y guía)

> Reglas generales del repo: [AGENTS.md](../../AGENTS.md) raíz. Este archivo explica la
> estructura de un slice y cómo crear uno nuevo.

## Qué es un slice

Una carpeta vertical con **una funcionalidad completa** de punta a punta: su negocio, sus
casos de uso, sus adapters y su punto de entrada. Unidad de organización y de aislamiento:
los slices **nunca se importan entre sí**; se comunican solo por
[`shared/contracts/`](../shared/contracts/) (verificado en CI).

```
src/slices/<slice>/
├── AGENTS.md            # Responsabilidad, ports, tablas, tools, errores, cómo probarlo
├── domain/              # Entidades, reglas de negocio, ports (Protocol/ABC). PURO.
├── application/         # Casos de uso: orquesta domain + ports. Sin AWS ni framework.
├── infrastructure/      # Adapters que implementan los ports (AWS, HTTP, canales).
└── handler/             # Entrada Lambda/evento + composición de dependencias.
```

Regla de dependencia: `handler → application → domain` y `infrastructure → domain`;
el dominio no importa nada externo (salvo stdlib, pydantic y `shared`).

## Índice de slices

| Slice | Responsabilidad | Paso | Estado |
|---|---|---|---|
| `conversation_gateway` | Entrada de mensajes Meta (3 canales), verificación/firma, `correlation_id`, resolución de tenant, respuesta al canal | 9 | definido |
| `supervisor` | Router de intención: saludo/smalltalk (ruta propia), ventas, citas, pedidos, FAQ | 4 | implementado |
| `customer_context` | Contexto del cliente por turno (`get_customer_context`) y su actualización | 4 | implementado |
| `tenant_prompts` | Prompts por tenant desde Prompt Management con fallback y rollback | fuera de ruta | definido |
| `knowledge_rag` | Retrieval sobre Aurora+pgvector y respuesta fundamentada con grounding (grafo `faq`) | 7 | implementado |
| `appointments` | Reservas/citas con confirmación y validación de horarios | 3 y 5 | implementado |
| `orders` | Pedidos: carrito, estado y la regla inmutable de la hora | 5 | implementado |
| `sentiment_handoff` | Sentimiento + reglas → `human_takeover` | fuera de ruta | definido |
| `abuse_protection` | Detección de abuso y bloqueo temporal con TTL | fuera de ruta | definido |
| `media_handling` | Imágenes/audios: descarga, S3, transcripción, envío | fuera de ruta | definido |
| `retention_archiving` | Hot (DynamoDB) → archivo (S3) → borrado; cierra ADR 0007 | fuera de ruta | definido |

Cada fila enlaza al `AGENTS.md` de su carpeta, que es su contrato funcional previo a la
implementación.

## Cómo crear un slice nuevo (paso a paso)

1. **Crea la carpeta** con los 4 paquetes y un `AGENTS.md` con las secciones:
   Responsabilidad · Entradas y salidas · Ports · Tablas y recursos · Reglas de negocio ·
   Tools expuestas al LLM · Errores esperados · Cómo probarlo (usa la plantilla de
   `src/slices/orders/AGENTS.md`).
2. **`__init__.py` con docstring de responsabilidad** en cada paquete
   (`tests/unit/test_repo_contract.py` falla si falta).
3. **`domain/` primero**: entidades Pydantic, reglas de negocio (aquí, nunca en prompts),
   ports como `Protocol`. Sin `boto3`, sin `langgraph`, sin HTTP.
4. **`application/`**: casos de uso; recibe los ports por inyección (constructor).
5. **`infrastructure/`**: adapters concretos (usan `adapters/` cuando son transversales).
6. **`handler/`**: recibe el evento (Lambda/API Gateway), resuelve/valida el contexto de
   tenant, compone dependencias (application + infrastructure) y ejecuta.
7. **Si habla con otro slice**: añade el mensaje en `shared/contracts/` (Pydantic) — nunca
   un import entre slices.
8. **Registra**: fila en la tabla de arriba, en la §2 de `AGENTS.md` raíz, y recursos AWS
   en `infra/` si aplica.
9. **Verifica**: `pytest tests/unit/test_repo_contract.py`, `lint-imports`, `mypy`,
   `ruff check src tests`.
10. **Tests mínimos**: unit del dominio (todas las reglas), contract si hay contrato, eval
    en `tests/agent_evals/datasets/` si cambia el comportamiento conversacional.

## Errores comunes (y por qué falla el CI)

- Importar un slice desde otro → `lint-imports` + test AST de aislamiento.
- `domain/` importando `boto3`/`langgraph`/adapters → contrato "Domain stays pure".
- `__init__.py` sin docstring → `test_repo_contract.py`.
- `infrastructure/` importando `application/` → contrato "Infrastructure never imports...".
