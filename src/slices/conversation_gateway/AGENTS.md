# Slice: conversation_gateway

> Paso de implementación: **Paso 9**. Estado: **Fases 1–4 hechas** (dominio, firma,
> parsers, tenant + dedup + encolado); fases 5–7 pendientes. Es la puerta única de
> entrada de la plataforma.

## Responsabilidad

Recibe los webhooks de Meta (WhatsApp, Instagram, Messenger), verifica su autenticidad,
asigna `correlation_id`, **resuelve el `tenant_id`**, normaliza el mensaje a un contrato
interno, lo entrega al pipeline (`supervisor`) y devuelve la respuesta al canal. NO decide
intenciones, NO ejecuta tools de negocio, NO contiene lógica de ventas/citas/pedidos.

## Entradas y salidas

- Entradas: webhook Meta (`hub.challenge` para verificación GET; POST con firma
  `X-Hub-Signature-256` y payload de mensajes/texto/media), respuesta del pipeline
  (contrato en `shared/contracts/`).
- Salidas: eventos encolados (`inbound.message` → cola SQS con DLQ) hacia el consumer;
  mensajes salientes al canal vía `ChannelPort`; logs estructurados con
  `correlation_id` + `tenant_id`.

## Ports

- Expone: contrato `InboundMessage`/`OutboundMessage` y `QueuedMessage`
  (`shared/contracts/`) — `QueuedMessage` es el `InboundMessage` ya tipado con
  `message_type`/`sender_name`/`media_*` y `raw_payload` (cuerpo firmado exacto, máx.
  200 000 chars) que va dentro del evento de SQS.
- Consume:
  - `NormalizerPort` (`domain/ports.py`): vista de entrada de `ChannelPort` —
    `normalize_inbound` (implementado por `MetaChannel` en `infrastructure/channels/`).
  - `TenantResolverPort`: mapeo canal→tenant replicado del legacy
    (`DynamoChannelMapping`), `TODO(verify)` del mecanismo de sincronización.
  - `DeduplicationPort`: `register_once` (reclamación atómica) + `release` (rollback si
    el encolado falla; sin esto, el reintento de Meta se perdería como duplicado).
  - `EventBusPort` de `shared/ports/` (implementado por `SQSEventBus` de
    `adapters/sqs/`).

## Tablas y recursos AWS

| Recurso | Por qué | Paso |
|---|---|---|
| API Gateway HTTP (`/webhook`) | Entrada pública del webhook Meta (verificación + firma) | 9/6 |
| SQS (cola de entrada) + DLQ | Desacoplar recepción de procesamiento y absorber picos (`inbound.message` con `{event, payload}`) | 9 |
| DynamoDB `chatbot_channel_mapping` | Mapeo id de emisor Meta → `store_id` (claves exactas del legacy `WA_CONFIG#<id>\|METADATA`, `IG_CONFIG#`, `FB_CONFIG#`) | 9 |
| DynamoDB `chatbot_processed_messages` | Deduplicación: `MSG_PROCESSED#<message_id>\|DEDUP#<tenant_id>` con `attribute_not_exists(PK)` y TTL 24 h | 9 |
| Secrets Manager/SSM | Secreto de verificación y tokens Meta (por tenant) | 5 (credenciales) |

## Reglas de negocio clave

1. El webhook **solo se acepta** si la firma HMAC es válida; si no → 403 + log de
   auditoría (obligatoria en todos los entornos, ADR 0006).
2. `tenant_id` se resuelve **una sola vez** aquí y viaja en el contexto de todo el turno;
   si algún mensaje del evento no tiene mapeo → `200 EVENT_TENANT_UNKNOWN` **sin encolar
   nada** (no se procesa a medias). `TODO(decision)`: la respuesta fija «comercio no
   disponible» no es posible sin credenciales del canal → pendiente de Fase 5.
3. Mensajes duplicados (mismo `message_id` por tenant) se descartan: se reclama la clave
   **antes** de encolar y se libera (`release`) si el envío a SQS falla, para que el
   reintento de Meta no se pierda. Si el evento completo es duplicado →
   `200 EVENT_DUPLICATED` (acuse silencioso, idempotencia).
4. Medios: solo atributos (`media_id`/`media_type`/`media_url`); la descarga a S3 la hace
   `media_handling`.
5. El canal es intercambiable: el dominio no sabe si es WhatsApp, IG o Messenger
   (ADR 0009); el despacho es `detect_channel` + registro `parse_event`.
6. Nunca se publica un evento sin resolver **todos** los tenants del envelope (dos pasos,
   sin encolado parcial).

## Tools expuestas al LLM

Ninguna. El gateway no expone tools; su único "efecto" sobre el LLM es entregar el
mensaje ya contextualizado.

## Errores esperados

| Error | Cuándo | Traducción |
|---|---|---|
| `InvalidSignatureError` | Firma Meta inválida | HTTP 403 + log (sin detalle al cliente) |
| `TenantNotFoundError` | Sin mapeo de canal (interno del resolve) | `200 EVENT_TENANT_UNKNOWN`, sin encolar |
| `DuplicateMessageError` | Reenvío íntegro de Meta | `200 EVENT_DUPLICATED` (idempotencia) |
| `ValidationError` | Cuerpo malformado o configuración faltante (fail fast) | HTTP 400 / excepción al arrancar |
| `ToolError`/`ToolTimeoutError` | Fallo de SQS o DynamoDB | Reintento de Meta + `release` de la dedup |
| Timeout de canal | Meta no responde (Fase 6) | Retry acotado + log; la respuesta se encola |

## Cómo probarlo

- Unit (`tests/unit/`): verificación de firma con payload falso, resolución de tenant con
  mapeo presente/ausente, deduplicación, flujo completo
  (`test_conversation_gateway_flow.py`) y adapters (`*_dynamodb.py`,
  `test_adapters_sqs_event_bus.py`) con dobles, sin AWS.
- Contract (`tests/contract/test_channel_parsers.py`): esquema del payload de webhook de
  los 3 canales (textos, media, estados de lectura).
- Eval (`tests/agent_evals/datasets/`): un saludo llega normalizado con `tenant_id` y
  `correlation_id` presentes (Fase 6, al conectar el consumer).
