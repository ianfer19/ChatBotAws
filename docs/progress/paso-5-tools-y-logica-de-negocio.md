# Progreso — Paso 5: Tools + lógica de negocio

> **Checklist vivo del Paso 5.** Se actualiza tras cada commit de la fase: `[x]` hecho,
> `[~]` en curso, `[ ]` pendiente. Es la respuesta rápida a «¿qué se hizo y qué falta?»
> sin releer el código. Criterio de cierre del paso:
> [ROADMAP §1 fila 5](../ROADMAP.md). Decisiones de alcance: ADR
> [0011](../adr/0011-confirmacion-por-politica-con-drafts.md).
>
> **Estado global: Fase 3 de 5 completada; siguiente: Fase 4 (router de confirmación).**

## Decisiones cerradas con el usuario (2026-10-09)

- [x] Grafo de pedidos incluido en el Paso 5 (especialista `orders` + `route_orders`).
- [x] Confirmación: **política de riesgo propose/commit con drafts** (no ritual fijo;
      no depende del checkpointer del Paso 8) → ADR 0011.
- [x] Ambos cierres del ROADMAP en este paso: eval «cambiar la hora» + endpoints
      exactos en `INTEGRATION_WITH_LEGACY.md` §4 (leyendo el legacy, solo lectura).

## Fase 1 — ADR 0011 + drafts compartidos

- [x] ADR 0011 (`docs/adr/0011-confirmacion-por-politica-con-drafts.md`) + índice ADR + AGENTS §8.
- [x] Contratos `PendingDraft`/`DraftStatus`/`ConfirmationPolicy`/`PolicyDecision` en `shared/contracts/pending.py`.
- [x] Puerto `DraftStorePort` en `shared/ports/draft.py`.
- [x] Doble `InMemoryDraftStore` en `src/adapters/in_memory/` (integridad del hash,
      un solo draft activo por conversación, commit solo desde AUTO/CONFIRMED, TTL).
- [x] Tests `tests/unit/test_shared_drafts.py` (17) + registro en AGENTS de `shared/` y `adapters/`.

## Fase 2 — appointments: propose/commit + reglas + estados

- [x] `domain`: solapes y horario (reglas 2 y 3), errores `SlotUnavailable`/`OutsideOpeningHours`,
      estados canónicos, `policy.py` (`decide`), `confirm_draft`/`cancel_draft`/`undo_draft`.
- [x] Tools: renombre `create_appointment` → `propose_appointment` (escribe draft +
      aplica política), commit idempotente; grafo/prompts/allowlist actualizados.
- [x] `LegacyOpsPort` (Protocol, endpoints del catálogo; sin HTTP hasta el Paso 11).
- [x] Tests unit actualizados + primeros `tests/contract/`.

## Fase 3 — orders: dominio + tools + grafo + enlace al supervisor

- [x] `domain`: carrito, mínimo, horario de cocina, disponibilidad, `PaymentRejected`,
      `LegacyTimeout`, política `decide`, estados canónicos (`TODO(verify)` en legacy).
- [x] `CatalogPort` + doble en memoria (precios sintéticos; jamás del LLM).
- [x] Tools `search_products`/`get_menu`/`get_order_status`/`propose_order`.
- [x] Grafo `build_order_graph` (espejo de citas) + `prompts/base/orders.md`.
- [x] Supervisor: `route_orders` + `orders_graph` en `build_supervisor_graph` (ADR 0010).
- [x] Regla crítica: sin tool de hora (capas 1–2 con test; 3–5 → Pasos 11/13).
- [x] Tests: `test_orders_{rules,policy,tools,drafts,graph}.py`,
      `tests/contract/test_orders_tools_contract.py` y casos `route_orders`/
      `route_pending` en `test_supervisor_graph.py`.

## Fase 4 — router de confirmación + allowlist por tenant

- [ ] Nodo `resolve_pending` del supervisor + `ConfirmerPort` (affirm/deny/modify,
      verificación de `payload_hash`, ventana de deshacer).
- [ ] `Deps.allowed_tools` en ambos especialistas (`select_action` interseca;
      composición deriva de `allowed_bots`).
- [ ] Tests: router (affirm/deny/hash desfasado/expirado/undo), tool deshabilitada,
      regresión de saludo intacta.

## Fase 5 — evals + contratos + endpoints legacy + docs + smoke

- [ ] Evals: «sin hora → pide confirmación» (criterio ROADMAP), «cambiar la hora de mi
      pedido» → sin tool + rechazo (capa 5), «lo de siempre» → AUTO sin ritual,
      monto alto → AWAITING.
- [ ] `tests/contract/`: `PendingDraft`, `OrderPropose`, `OrderView` (+ rechazo de
      campos de hora/tenant).
- [ ] `INTEGRATION_WITH_LEGACY.md` §4: endpoints Sales/Product (catálogo) y Ops
      (leyendo `sahagunonline/back/src/ops_service/app.py`); no confirmado → `TODO(verify)`.
- [ ] Docs: AGENTS de appointments/orders/supervisor + índice de slices, raíz
      §1/§8/§10 fila 5 → **hecho**, CLAUDE paso activo → **6**, changelog de prompts (§5.11).
- [ ] Smoke real con `iastock-old`: REPL con turno de pedido (proponer → auto/confirmar)
      + supervisor smoke extendido.

## Criterios de hecho del ROADMAP (§1 fila 5)

- [ ] Unit de dominio + eval «sin hora → pide confirmación» en verde.
- [ ] Adapter legacy **pendiente** pero con endpoints levantados de `catalogo_endpoints.md`.
- [ ] Batería completa en verde (ruff, format, mypy, pytest, lint-imports, terraform,
      pyrefly, final_review).
