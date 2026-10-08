# Slice: conversation_gateway

> Paso de implementación: **Paso 9**. Estado: **definido, sin implementar**. Es la puerta
> única de entrada de la plataforma.

## Responsabilidad

Recibe los webhooks de Meta (WhatsApp, Instagram, Messenger), verifica su autenticidad,
asigna `correlation_id`, **resuelve el `tenant_id`**, normaliza el mensaje a un contrato
interno, lo entrega al pipeline (`supervisor`) y devuelve la respuesta al canal. NO decide
intenciones, NO ejecuta tools de negocio, NO contiene lógica de ventas/citas/pedidos.

## Entradas y salidas

- Entradas: webhook Meta (`hub.challenge` para verificación GET; POST con firma
  `X-Hub-Signature-256` y payload de mensajes/texto/media), respuesta del pipeline
  (contrato en `shared/contracts/`).
- Salidas: eventos encolados (SQS) hacia el supervisor; mensajes salientes al canal vía
  `ChannelPort`; logs estructurados con `correlation_id` + `tenant_id`.

## Ports

- Expone: contrato `InboundMessage`/`OutboundMessage` (`shared/contracts/`).
- Consume: `ChannelPort` (envío; implementado por `infrastructure/channels/`), puerto de
  resolución de tenant (mapeo canal→tenant replicado del legacy, `TODO(verify)` del
  mecanismo), `EventBusPort` de `shared/ports/`.

## Tablas y recursos AWS

| Recurso | Por qué | Paso |
|---|---|---|
| API Gateway HTTP (`/webhook`) | Entrada pública del webhook Meta (verificación + firma) | 6 |
| SQS (cola de entrada) | Desacoplar recepción de procesamiento y absorber picos | 6 |
| DynamoDB `channel_mapping` | Mapeo id de emisor Meta → `store_id` (réplica del legacy `WA_CONFIG#`/`IG_CONFIG#`/`FB_CONFIG#`) | 6/9 |
| Secrets Manager/SSM | Secreto de verificación y tokens Meta (por tenant) | 6 |

## Reglas de negocio clave

1. El webhook **solo se acepta** si la firma HMAC es válida; si no → 403 + log de auditoría.
2. `tenant_id` se resuelve **una sola vez** aquí y viaja en el contexto de todo el turno;
   si no hay mapeo → mensaje de "comercio no configurado" sin invocar al agente.
3. Mensajes duplicados (mismo `message_id`) se descartan (idempotencia).
4. Medios: se delegan a `media_handling` (el gateway solo normaliza el evento).
5. El canal es intercambiable: el dominio no sabe si es WhatsApp, IG o Messenger (ADR 0009).

## Tools expuestas al LLM

Ninguna. El gateway no expone tools; su único "efecto" sobre el LLM es entregar el
mensaje ya contextualizado.

## Errores esperados

| Error | Cuándo | Traducción |
|---|---|---|
| `InvalidSignatureError` | Firma Meta inválida | HTTP 403 + log (sin detalle al cliente) |
| `TenantNotFoundError` | Sin mapeo de canal | Respuesta fija de comercio no disponible |
| `DuplicateMessageError` | Reenvío de Meta | 200 OK silencioso (idempotencia) |
| Timeout de canal | Meta no responde | Retry acotado + log; la respuesta se encola |

## Cómo probarlo

- Unit (`tests/unit/`): verificación de firma con payload falso, resolución de tenant con
  mapeo presente/ausente, deduplicación.
- Contract (`tests/contract/`): esquema del payload de webhook de los 3 canales
  (textos, media, estados de lectura).
- Eval (`tests/agent_evals/datasets/`): un saludo llega normalizado con `tenant_id` y
  `correlation_id` presentes.
