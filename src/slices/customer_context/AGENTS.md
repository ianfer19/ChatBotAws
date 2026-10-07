# Slice: customer_context

> Fase de implementación: **Fase 4**. Estado: **definido, sin implementar**. Responsable
> del contexto obligatorio de cada turno.

## Responsabilidad

Persistir y recuperar el contexto del cliente (preferencias, datos de contacto, últimos
eventos relevantes) en DynamoDB y exponerlo al agente como **tool de LangGraph**
(`get_customer_context`), además de actualizarlo tras eventos relevantes. NO es fuente de
verdad de negocio: precios, stock, pedidos y horas vienen del legacy/dominio.

## Entradas y salidas

- Entradas: eventos del pipeline (turno en curso, "pedido creado", "cita agendada"),
  llamadas a la tool `get_customer_context` desde cualquier agente.
- Salidas: `CustomerContext` (modelo Pydantic) inyectado en el state de LangGraph;
  escrituras de contexto en DynamoDB.

## Ports

- Expone: tool `get_customer_context` (contrato en `shared/contracts/`) y caso de uso
  `update_customer_context`.
- Consume: `shared.ports` de persistencia (implementado en `adapters/dynamodb`),
  contratos de eventos de otros slices (solo los consume; no importa sus módulos).

## Tablas y recursos AWS

| Recurso | Por qué | Fase |
|---|---|---|
| DynamoDB `customer_context` (PK `ORG#<tenant_id>#CUST#<phone>`) | Contexto por cliente y tenant, baja latencia | 3 |
| DynamoDB (TTL) | Caducidad de contexto inactivo | 3 |

## Reglas de negocio clave

1. **Contexto obligatorio en cada turno**: el prompt de todo agente recibe (a) el resultado
   de `get_customer_context` y (b) el historial con ventana controlada + resumen. Existe un
   test que **falla** si un turno llega sin uno de los dos (requisito 7.2).
2. El contexto **nunca** contiene verdad operacional (precios/stock/pedidos/horas): solo
   preferencias y datos identificativos del cliente.
3. Toda lectura/escritura filtra por `tenant_id`: un cliente de un comercio jamás se lee
   desde otro.
4. La tool `get_customer_context` es de **lectura** para el LLM; la escritura solo ocurre
   desde casos de uso (eventos), no desde una herramienta que el modelo pueda invocar
   arbitrariamente.
5. La memoria largo plazo (AgentCore Memory, Fase 8) es complementaria: lo que importa
   operacionalmente vive aquí, no en la memoria del modelo.

## Tools expuestas al LLM

| Tool | Esquema | Notas |
|---|---|---|
| `get_customer_context` | `() -> CustomerContext` (sin parámetros: el cliente sale del contexto) | Lectura; timeout corto; log con `correlation_id` |

## Errores esperados

| Error | Cuándo | Traducción |
|---|---|---|
| `CustomerContextNotFound` | Cliente nuevo / sin historial | Contexto vacío por defecto (no es error) |
| `ContextStaleError` | TTL vencido | Contexto vacío + relectura en el siguiente turno |
| Timeout DynamoDB | Caída de servicio | Turno continúa SIN contexto + log de degradación |

## Cómo probarlo

- Unit (`tests/unit/`): CRUD con reloj controlado (`ClockPort`), aislamiento por tenant.
- Contract: esquema de `CustomerContext` (round-trip).
- Eval (`tests/agent_evals/datasets/`): **caso obligatorio de contexto ausente**: si el
  prompt se construye sin contexto ni historial, el test falla (requisito 7.2).
