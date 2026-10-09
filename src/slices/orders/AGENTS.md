# Slice: orders

> Paso de implementación: **Paso 5**. Estado: **Paso 5 completo (Fases 1–5)**: dominio,
> tools propose/commit, grafo, enlace `route_orders`, `Deps.allowed_tools` con
> intersección en `select_action`, router `resolve_pending` del supervisor, evals y
> contratos. Pendiente en la ruta: adapter legacy real (Paso 11), catálogo desde
> RAG/Aurora (Paso 7).

## Responsabilidad
Pedidos del comercio: catálogo, consulta de estado y creación con confirmación humana
del carrito. No modifica la hora de un pedido (regla crítica protegida por defensa en
profundidad), no calcula precios ni stock (los aporta el backend legacy) y no decide la
intención ni redacta la respuesta final.

## Entradas y salidas
- Entradas: llamadas a las tools del especialista de pedidos (`search_products`,
  `get_menu`, `get_order_status`, `propose_order`) con el contexto ya resuelto
  (`tenant_id`, `correlation_id`, `conversation_id`) entregado por `shared/context` y
  con el `message` crudo del cliente (la política detecta ítems inferidos).
- Salidas: `ToolResult` con el pedido/`products`/`order` ya materializados o solo el
  draft (`draft_id`, `draft_status`, `policy`); logs de auditoría con `correlation_id`
  y `tenant_id`.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): contratos de catálogo y
  pedidos (`ProductView`, `OrderView`, `ToolResult`; `TODO(decision)` si se promueven a
  `shared/contracts/`). **No existe** ni contrato ni port de cambio de hora.
- Consume: `OrderRepositoryPort`, `CatalogPort` y `LegacyOrdersPort` (Protocol en
  `domain/ports.py` — APIs Sales/Product del legacy, **sin HTTP hasta el Paso 11**,
  `TODO(verify)`), `DraftStorePort` de `shared/ports/` (implementación hoy
  `adapters/in_memory.InMemoryDraftStore`; DynamoDB `pending_actions` en el Paso 6) y
  `adapters/bedrock` (solo redacción).
- Definidos en el **Paso 1**: `domain/entities.py` (`Order`, `OrderItem`,
  `OrderStatus = Literal["ABIERTA", "CERRADA", "ANULADA"]`, `Product`),
  `domain/ports.py` (`OrderRepositoryPort`), `infrastructure/in_memory.py`
  (`InMemoryOrderRepository`).
- Definidos en la **Fase 3 del Paso 5**: `domain/hours.py` (`KitchenHoursDay`),
  `domain/rules.py` (`validate_cart`, `check_minimum`, `within_kitchen_hours`,
  `MINIMO_COMPRA`), `domain/policy.py` (`detect_inferred_items`, `decide_order`,
  `MONTO_UMBRAL`, `MOTIVO_MONTO`), `domain/errors.py` (`EmptyCart`,
  `ProductUnavailable`, `OutsideKitchenHours`, `MinimumNotMet`, `OrderNotFound`,
  `PaymentRejected`, `LegacyTimeout`, `DraftNotFound`, `DraftNotCommittable`),
  `domain/ports.py` (`CatalogPort`, `LegacyOrdersPort`), `application/` (`state.py`,
  `schemas.py`, `prompts.py`, `tools.py`, `drafts.py`, `deps.py`, `nodes/`, `graph.py`)
  e `infrastructure/in_memory.py` (`InMemoryLegacyOrders`, `InMemoryCatalog`).

## Grafo (Fase 3 del Paso 5)
- `application/graph.py` → `build_order_graph(llm, legacy, catalog, clock,
  kitchen_hours, drafts, minimum=MINIMO_COMPRA, amount_threshold=MONTO_UMBRAL,
  allowed_tools=None)`.
  Nodos en `application/nodes/`: `understand` (LLM → JSON validado en `OrderProposal`,
  con reintento y degradación a aclaración; el `system` incluye «ahora es `YYYY-MM-DD`
  (día)» con el `ClockPort` para juzgar el horario de cocina), `validate` + `need_more?`
  (carrito obligatorio para proponer; `query`/`order_id` según la tool), `select_action`
  (allowlist `ALLOWED_TOOLS` intersecada con `Deps.allowed_tools` — mínimo privilegio
  por comercio; sin `tool_name` si no aplica), `call_tool` (despacho con
  `conversation_id`/`message`; un `AppError` se traduce en `tool_error`),
  `validate_result` + `needs_confirmation?` (coherencia; la confirmación sale del
  `draft_status`) y `respond` (redacción: espera confirmación si el draft está
  `AWAITING_CONFIRMATION`, entrega si `COMMITTED`).
- `AgentState` (`application/state.py`): el llamador pone `tenant_id`, `correlation_id`,
  `conversation_id`, `user_message` y `history`; el resto lo escriben los nodos.
  `conversation_id` es **requerido**: es la ranura única de drafts (compuesto
  `canal:customer_id` en `supervisor/route_orders` hasta el Paso 9, `TODO(verify)`).
- Dos llamadas al LLM por turno (interpretar y redactar). **Sin checkpointer**
  (`TODO(decision)`: multi-turno con checkpointer en el Paso 8).
- Confirmación (ADR 0011): `propose_order` nunca escribe el pedido directamente: crea
  un `PendingDraft` y el dominio decide `AUTO` (commit inmediato con `VENTANA_DESHACER`
  de 30 min) o `CONFIRM` (draft `AWAITING_CONFIRMATION` que confirmará el router del
  supervisor en la Fase 4); `confirm_draft` exige el `payload_hash`.
- Supervisor (`supervisor/application/graph.py`): `build_supervisor_graph(...,
  orders_graph=None)` añade el nodo `route_orders` (nodo anidado, ADR 0010); `None`
  deja los pedidos en `route_pending` (retrocompatible). El router
  `supervisor/domain/ports.py::ConfirmerPort` (`affirm`/`deny`/`undo`) confirma y
  deshace los drafts de este slice con el `payload_hash` exacto (Fase 4, ADR 0011 §5).

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| Aurora PostgreSQL (tabla `orders`) | Estado y trazabilidad del pedido | 6 |
| DynamoDB `pending_actions` (TTL 24 h) | Drafts propose/commit (`DraftStorePort`) | 6 |
| DynamoDB `order_locks` (TTL) | Idempotencia de `propose_order` por `correlation_id` | 6 |
| APIs legacy Sales/Product vía AgentCore Gateway + Policy | Catálogo, estado y creación reales (`LegacyOrdersPort` hoy sin HTTP) | 11 |
| Bedrock Guardrails (tema denegado: cambiar hora del pedido) | Defensa en profundidad de la regla crítica | 13 |
| CloudWatch Logs | Auditoría de tools y de rechazos del domain | 5 |

## Reglas de negocio clave
1. **Defensa en profundidad**: no existe tool de cambio de hora (allowlist
   `ALLOWED_TOOLS` sin ninguna tool de hora, con test); `Order` en domain no expone esa
   operación (test de campos); AgentCore Policy la deniega (default-deny, Paso 11);
   Guardrails tiene el tema denegado (Paso 13); test de regresión que falla si se
   retira una capa (ver `../../../AGENTS.md` §7).
2. Todo filtro y toda operación usan el `tenant_id` del contexto, nunca el del payload
   del LLM (hay test de contrato: el esquema rechaza `tenant_id` y claves de más).
3. **Política de riesgo (ADR 0011)**: si algún ítem no fue dicho literalmente por el
   cliente (`detect_inferred_items`: ni SKU ni nombre en el mensaje), o el total supera
   `MONTO_UMBRAL` (100 000, `TODO(decision)`), la propuesta va `CONFIRM` con motivos
   `item_inferido:<sku>`/`monto_sobre_umbral`; si todo lo dijo el cliente y el monto es
   bajo, `AUTO` con ventana de deshacer. Nada depende solo del prompt.
4. El domain valida carrito no vacío, cantidades positivas, productos disponibles,
   mínimo de compra (`MINIMO_COMPRA`, `TODO(decision)`) y horario de cocina
   (`KitchenHoursDay`, extremos inclusivos) antes de crear draft o tocar el backend.
5. Precios, stock y disponibilidad provienen del catálogo legacy; jamás del LLM.
6. `get_order_status` solo devuelve pedidos del propio tenant (`OrderNotFound` si no
   existe o es ajeno, sin detalles del ajeno).
7. Un pago rechazado por el legacy se informa tal cual; nunca se reintenta en bucle.
8. `undo_draft` anula el pedido creado solo mientras esté `ABIERTA` y dentro de la
   ventana de 30 min (`DraftNotCommittable` en caso contrario).

## Tools expuestas al LLM
| Tool | Esquema resumido | Notas de seguridad |
|---|---|---|
| `search_products` | `{query}` → `[product]` | Solo lectura; el precio siempre viene del catálogo |
| `get_menu` | `{category?}` → `[product]` | Filtra por `tenant_id` del contexto |
| `get_order_status` | `{order_id}` → `order` | Autoriza por tenant; no expone pedidos ajenos |
| `propose_order` | `{items: [{sku, quantity}], message, conversation_id}` → pedido o draft | Escribe **solo** como draft; política `AUTO`/`CONFIRM`; idempotente por `correlation_id`; valida carrito, mínimo y horario de cocina |
| — | **No existe** tool para modificar la hora de un pedido | Capa 1 de la defensa en profundidad |

Ninguna tool acepta `tenant_id` en el payload: siempre es argumento del contexto (hay un
test de contrato que falla si aparece `**kwargs`, `tenant_id` o campos de hora).

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `EmptyCart` | Carrito sin ítems | "Agrega al menos un producto" + log info |
| `ProductUnavailable` | SKU sin stock o fuera del catálogo | Sugerir alternativa + log warn |
| `OutsideKitchenHours` | Fuera del horario de cocina | Informar el horario + log warn |
| `MinimumNotMet` | No alcanza el mínimo de compra | Informar el mínimo + log info |
| `OrderNotFound` | Pedido inexistente en este comercio | Rechazo genérico sin detalles + log info |
| `PaymentRejected` | El legacy rechaza el pago | Mensaje del legacy sin reintentos + log warn |
| `LegacyTimeout` | `sales_service` no responde en el timeout | Disculpa al usuario + log error con `correlation_id` |
| `DraftNotFound` | No hay draft con ese id en el comercio | "La propuesta ya no está disponible" + log warn |
| `DraftNotCommittable` | Transición ilegal (commit desde `DRAFTED`, undo fuera de ventana o pedido ya cerrado…) | "La propuesta ya no admite cambios" + log warn |

Los errores de tool llegan a `respond` como `tool_error` (`code` + mensaje interno con
9 códigos con pista en el prompt): el turno nunca se rompe por un fallo de negocio.

## Cómo probarlo
- `tests/unit/` (Paso 1, hecho): `test_orders_repository.py` — el doble cumple el
  port, aislamiento por tenant, idempotencia por `correlation_id`, cantidades no
  positivas y **regresión de la capa 2**: `Order` no expone ningún campo de hora.
- `tests/unit/` (Fase 3, hecho): `test_orders_rules.py` (carrito, mínimo, horario de
  cocina), `test_orders_policy.py` (detección de ítems inferidos y política
  AUTO/CONFIRM con motivos),   `test_orders_tools.py` (lecturas, propose/commit,
  idempotencia, mínimo, horario, monto alto, allowlist sin tool de hora),
  `test_orders_drafts.py` (confirm con hash, commit, cancel, undo dentro/fuera de
  ventana, pedido cerrado) y `test_orders_graph.py` (nodos sueltos y end-to-end:
  saludo, propuesta inferida a la espera, `AUTO` con literales, menú con precios
  reales, JSON con `tenant_id` ajeno).
- `tests/contract/` (Fase 3, hecho): `test_orders_tools_contract.py` — la propuesta
  rechaza `tenant_id` y cualquier clave de hora (`scheduled_at`, `hora`, …) incluso
  dentro de `items`, el `ToolResult` es inmutable y `propose_order` solo admite
  argumentos nombrados y anotados.
- Supervisor (Fase 3, hecho): `tests/unit/test_supervisor_graph.py` — `route_orders`
  invoca el especialista con los ids resueltos; sin `orders_graph` el turno cae en
  `route_pending` sin reply.
- Fase 4 (hecho): tool deshabilitada en `tests/unit/test_orders_graph.py`
  (`test_select_action_recorta_las_tools_por_el_comercio` y
  `test_e2e_tool_fuera_del_entitlement_no_ejecuta_ni_se_inventa`) y router
  `resolve_pending` en `tests/unit/test_supervisor_resolve_pending.py`.
- Fase 5 (hecho): `tests/agent_evals/datasets/orders_behavior.json` con su ejecutor
  `tests/agent_evals/test_orders_dataset.py` («cambiar la hora» → sin tool ni
  invocaciones y rechazo honesto, `order_time_01/02`; «lo de siempre» → `AUTO` con
  commit, `order_lo_de_siempre_01`; monto alto → `AWAITING`, `order_monto_alto_01`) y
  contrato de `PendingDraft`/`OrderView`/`OrderProposal` en
  `tests/contract/test_pending_contracts.py`.
- Manual contra Bedrock (hecho el 2026-10-09, cuenta `iastock-old`): REPL
  `python scripts\chat_citas.py` con `orders_graph`/`confirmer`/`draft_store`
  cableados — «quiero 2 A-100 y 1 P-100» → `AUTO` con pedido `ABIERTA` (41 000) y
  «quiero 6 A-100» → `AWAITING` + «sí» del router → pedido creado (108 000); y smoke
  `pytest tests/integration -rs` (`5 passed`).
