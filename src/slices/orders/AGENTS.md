# Slice: orders

> Paso de implementación: **Paso 5**. Estado: **definido, sin implementar** (el detalle
> funcional se completa en su paso; este documento es el contrato previo).

## Responsabilidad
Pedidos del comercio: catálogo, consulta de estado y creación con confirmación humana
del carrito. No modifica la hora de un pedido (regla crítica protegida por defensa en
profundidad), no calcula precios ni stock (los aporta el backend legacy) y no decide
la intención ni redacta la respuesta final.

## Entradas y salidas
- Entradas: tools del especialista de pedidos (`search_products`, `get_menu`,
  `get_order_status`, `create_order`) con `tenant_id` y `correlation_id` del contexto
  resuelto por el gateway.
- Salidas: pedidos creados y consultados en las APIs del legacy vía
  `adapters/legacy_backend` (AgentCore Gateway + Policy); catálogo desde RAG o legacy;
  logs de auditoría con `correlation_id` y `tenant_id`.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): `ProductQuery`, `OrderView`,
  `OrderCreateRequest` / `OrderConfirmation` (TODO(decision): nombres finales). No
  existe contrato ni port de cambio de hora.
- Consume: `VectorStorePort` (catálogo en Aurora; adapter `adapters/aurora`), ports del
  propio domain (`LegacyOrdersPort`, `OrderRepositoryPort`, `ClockPort`) y adapters
  `adapters/legacy_backend` (negocio real) y `adapters/bedrock` (solo redacción).
- Definidos en el **Paso 1**: `domain/entities.py` (`Order`, `OrderItem`),
  `domain/ports.py` (`OrderRepositoryPort`) e
  `infrastructure/in_memory.py` (`InMemoryOrderRepository`, el doble con el que corren
  los tests hasta que exista el adapter real en el Paso 6). `LegacyOrdersPort` y los
  contratos expuestos llegan con el Paso 5.

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| APIs legacy de pedidos vía AgentCore Gateway + Policy | Catálogo, estado, creación y pago reales | 11 |
| Aurora PostgreSQL (tabla `orders`) | Estado y trazabilidad del pedido | 6 |
| DynamoDB `order_locks` (TTL) | Idempotencia de `create_order` por `correlation_id` | 6 |
| Bedrock Guardrails (tema denegado: cambiar hora del pedido) | Defensa en profundidad de la regla crítica | 13 |
| CloudWatch Logs | Auditoría de tools y de rechazos del domain | 5 |

## Reglas de negocio clave
1. **Defensa en profundidad**: no existe tool de cambio de hora; `Order` en domain no
   expone esa operación; AgentCore Policy la deniega (default-deny); Guardrails tiene el
   tema denegado; test de regresión que falla si se retira una capa (ver
   `../../../AGENTS.md` §7).
2. Todo filtro y toda operación usan el `tenant_id` del contexto, nunca el del payload
   del LLM.
3. `create_order` exige confirmación humana del carrito (ítems, cantidades y total)
   antes de tocar el backend.
4. Precios, stock y disponibilidad provienen del legacy o del RAG; jamás del LLM.
5. El domain valida carrito no vacío, cantidades positivas y productos disponibles
   antes de cualquier llamada externa.
6. Mínimo de compra y horario de cocina se validan en domain (valores iniciales:
   TODO(decision)).
7. Un pago rechazado por el legacy se informa tal cual; nunca se reintenta en bucle.

## Tools expuestas al LLM
| Tool | Esquema resumido | Notas de seguridad |
|---|---|---|
| `search_products` | `{query}` → `[{product, price}]` | Solo lectura; el precio siempre viene del legacy/RAG |
| `get_menu` | `{category?}` → `[product]` | Filtra por `tenant_id` del contexto |
| `get_order_status` | `{order_id}` → estado | Autoriza por tenant; no expone pedidos ajenos |
| `create_order` | `{items: [{sku, qty}]}` → pedido | Confirmación humana previa; idempotente por `correlation_id`; timeout |
| — | **No existe** tool para modificar la hora de un pedido | Capa 1 de la defensa en profundidad |

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `EmptyCart` | Carrito sin ítems | "Agrega al menos un producto" + log info |
| `ProductUnavailable` | SKU sin stock o fuera del catálogo | Sugerir alternativa + log warn |
| `OutsideKitchenHours` | Fuera del horario de cocina | Informar el horario + log warn |
| `MinimumNotMet` | No alcanza el mínimo de compra | Informar el mínimo + log info |
| `PaymentRejected` | El legacy rechaza el pago | Mensaje del legacy sin reintentos + log warn |
| `LegacyTimeout` | `ops_service` no responde en el timeout | Disculpa al usuario + log error con `correlation_id` |

## Cómo probarlo
- `tests/unit/` (Paso 1, hecho): `test_orders_repository.py` — el doble cumple el port,
  aislamiento por tenant, idempotencia por `correlation_id`, cantidades no positivas
  rechazadas y **regresión de la capa 2**: `Order` no expone ningún campo de hora.
- `tests/unit/`: domain de `orders` — `Order` no expone ninguna operación de cambio de
  hora, carrito vacío rechazado, mínimo de compra y horario de cocina.
- `tests/contract/`: esquemas de `OrderCreateRequest` y `OrderView`, y rechazo de
  payloads que traigan campos de cambio de hora.
- `tests/agent_evals/datasets/`: caso negativo obligatorio "cambiar la hora de mi
  pedido" → rechazo en domain, sin tool invocada y respuesta correcta; además el test
  de regresión de las cinco capas.
