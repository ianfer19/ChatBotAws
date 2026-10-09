# Progreso — Paso 5: Tools + lógica de negocio

> **Checklist vivo del Paso 5.** Se actualiza tras cada commit de la fase: `[x]` hecho,
> `[~]` en curso, `[ ]` pendiente. Es la respuesta rápida a «¿qué se hizo y qué falta?»
> sin releer el código. Criterio de cierre del paso:
> [ROADMAP §1 fila 5](../ROADMAP.md). Decisiones de alcance: ADR
> [0011](../adr/0011-confirmacion-por-politica-con-drafts.md).
>
> **Estado global: PASO 5 COMPLETO (Fases 1–5).** Siguiente en la ruta:
> [ROADMAP](../ROADMAP.md) Paso 6 (infraestructura Terraform base).

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

- [x] Nodo `resolve_pending` del supervisor + `ConfirmerPort` (affirm/deny/undo;
      verificación de `payload_hash` contra `TAREA_PENDIENTE`, plantillas de respuesta
      genéricas, ventana de deshacer; `modify`/supersede lo gestiona el especialista al
      proponer de nuevo, ADR 0011 §5).
- [x] `Deps.allowed_tools` en ambos especialistas (`select_action` interseca con la
      allowlist del slice; `respond` redacta «no está habilitada» sin inventar);
      la derivación de `allowed_bots` en la composición queda para el cableado de
      Fase 5 (`scripts/chat_citas.py`).
- [x] Tests: `test_supervisor_resolve_pending.py` (28: afirm/deny/hash desfasado/
      JSON ilegible/fallo del LLM/expirado/undo en y fuera de ventana/router no
      inyectado/confirmer caído + e2e «sí» sin clasificador y saludo intacto con draft
      esperando) y tool deshabilitada en `test_orders_graph.py` y
      `test_appointments_graph.py` (nodo `select_action` + e2e).

## Fase 5 — evals + contratos + endpoints legacy + docs + smoke

- [x] Evals: «sin hora → pide confirmación» (`appt_sin_hora_01`, criterio ROADMAP),
      «cambiar la hora de mi pedido» → sin tool + rechazo honesto (`order_time_01/02`,
      capa 5), «lo de siempre» → AUTO sin ritual (`order_lo_de_siempre_01`), monto alto
      → AWAITING (`order_monto_alto_01`) + inferido → CONFIRM
      (`appt_hora_inferida_01`); datasets `orders_behavior.json` /
      `appointments_behavior.json` con ejecutores punta a punta por el supervisor real.
- [x] `tests/contract/test_pending_contracts.py`: `PendingDraft` (inmutable, `extra="forbid"`,
      hash canónico, sin campos de hora), `OrderView` y `OrderProposal` (+ rechazo de
      campos de hora/tenant ya cubierto en `test_orders_tools_contract.py`).
- [x] `INTEGRATION_WITH_LEGACY.md` §4: endpoints Sales/Product/Ops levantados de
      `catalogo_endpoints.md` + código (`sales_service`, `product_service`,
      `ops_service`, `tenant_service`); todo lo no confirmado → `TODO(verify)`.
- [x] Cableado de `scripts/chat_citas.py`: `orders_graph`, `draft_store` compartido,
      `confirmer` real (despacho por `kind`), `allowed_tools ← allowed_bots`,
      catálogo/horario demo, `/status` con pedidos y salida de consola tolerante a
      caracteres fuera de la codepage (emoji del modelo no rompe el REPL).
- [x] Docs: AGENTS de appointments/orders/supervisor + índice de slices (fila
      appointments/orders → implementado), raíz §1/§10 fila 5 → **hecho**, CLAUDE paso
      activo → **6** (y ADR 0001–0011), READMEs de evals, INTEGRATION §2 y changelogs
      de `prompts/base/{orders,appointments}.md`.
- [x] Smoke real con `iastock-old` (2026-10-09): REPL multi-turno — «2 A-100 y 1 P-100»
      → pedido `ABIERTA` 41 000 (`AUTO`) y «6 A-100» → `AWAITING` + «sí» →
      `affirmed` con pedido 108 000; supervisor smoke extendido con `route_orders`
      (`pytest tests/integration -rs` → `5 passed`).

## Criterios de hecho del ROADMAP (§1 fila 5)

- [x] Unit de dominio + eval «sin hora → pide confirmación» en verde.
- [x] Adapter legacy **pendiente** (Paso 11) pero con endpoints levantados de
      `catalogo_endpoints.md` en INTEGRATION §4.
- [x] Batería completa en verde (ruff, format, mypy, pytest, lint-imports, terraform,
      pyrefly, final_review).
