# Progreso — Paso 9: Conversation gateway

> **Checklist vivo del Paso 9.** Se actualiza tras cada commit de la fase: `[x]` hecho,
> `[~]` en curso, `[ ]` pendiente. Es la respuesta rápida a «¿qué se hizo y qué falta?»
> sin releer el código. Criterio de cierre del paso:
> [ROADMAP §1 fila 9](../ROADMAP.md). Decisiones de alcance: este mismo archivo.
>
> **Estado global: PASO 9 EN CURSO — Fase 4 COMPLETA (4 de 7). Siguiente: Fase 5
> (credenciales SSM + endpoint admin + `verify_credentials`).**

## Decisiones cerradas con el usuario (2026-10-10)

1. [x] **Pipeline completo**: webhook Meta → SQS (+DLQ) → consumer → supervisor
   (Bedrock) → respuesta al canal. Nada de procesamiento inline en el webhook.
2. [x] **Estructura de datos = legacy** (con la arquitectura del repo): claves
   `WA_CONFIG#<phone_number_id>|METADATA` / `IG_CONFIG#` / `FB_CONFIG#` → `store_id`;
   mensajes con `raw_payload`, `sender`, `media_id/media_type/media_url`,
   `correlation_id`; dedup `MSG_PROCESSED#<message_id>|DEDUP` con
   `attribute_not_exists` + TTL 24 h (**clave por tenant**: el legacy es global y aquí
   rige la regla de aislamiento); credenciales en SSM SecureString
   `/sahagun/{canal}/{tenant}/access_token|app_secret`. Todo tras ports del slice.
3. [x] **Respuesta al canal copiando el `whatsapp_webhook_service` legacy**
   (`sahagunonline/back/src/whatsapp_webhook_service`): Cloud API
   `POST graph.facebook.com/v24.0/{phone_number_id}/messages` con token en header para
   texto, IG con token en query, estados de lectura ignorados, respuestas del consumer
   con `batchItemFailures`. **Diferencia deliberada**: la firma HMAC es **obligatoria y
   activa** en todos los entornos (el legacy la tiene comentada en `app.py:65-68`; el
   ADR 0006 no permite desactivarla).
4. [x] **Sin prueba de tráfico real en este cierre**: se crea un **endpoint admin**
   (`POST /admin/channels`) para que los usuarios carguen sus credenciales (IG/WA/etc.)
   en dev — escribe SSM y crea el mapping. El criterio «prueba con tráfico real de los
   3 canales» queda **pendiente de entorno dev**.
5. [x] **Media (fotos, videos, notas de voz): solo atributos** — el gateway normaliza y
   persiste `media_id`/`media_type`/`media_url` en el mensaje; la descarga a S3 y la
   transcripción quedan en `media_handling` (fuera de la ruta, ROADMAP §4).
6. [x] **Endpoint admin sin authorizer completo** (dev): token propio mínimo, sin
   validación contra Meta antes de guardar (`TODO(verify)`).

## Refinamiento de las fases (vs. el plan inicial de 5)

- **7 fases en vez de 5**: (a) los parsers de canal suben a la Fase 3 —antes que
  tenant/dedup— porque el flujo necesita normalizar el payload para obtener
  `emitter_id` y `message_id`; (b) credenciales + endpoint admin se separan a la Fase 5.
- Cada fase = 1 commit + batería verde antes de avanzar.

| Fase | Alcance | Estado |
|---|---|---|
| 1 | Domain + `ChannelPort` + errores + dobles en memoria | `[x]` |
| 2 | Webhook: `GET hub.challenge` + `POST` con firma HMAC | `[x]` |
| 3 | Normalización: parsers de los 3 canales → `ChannelMessage` | `[x]` |
| 4 | Tenant + dedup + encolado + módulo SQS/IAM (Terraform) | `[x]` |
| 5 | Credenciales (SSM) + endpoint admin + `verify_credentials` | `[ ]` |
| 6 | Consumer (persistencia + supervisor) + envío de respuestas + zips | `[ ]` |
| 7 | Cierre: AGENTS, ROADMAP, checklist, batería final | `[ ]` |

## Fase 1 — domain + `ChannelPort`  (hecha)

- [x] `shared/ports/channel.py`: `ChannelMessage` (mensaje normalizado **antes** de
  resolver tenant/correlación; vive en el port porque lo devuelve, como `LLMMessage` en
  `llm.py`) + `ChannelPort` (`normalize_inbound`/`send`/`verify_credentials`; la
  «clasificación de tipo de mensaje» del ADR 0009 es el campo `message_type`).
- [x] `domain/errors.py`: `InvalidSignatureError` (403), `DuplicateMessageError`
  (http 200: no es un error para Meta, es un acuse silencioso).
- [x] `domain/signature.py`: `is_valid_signature` — HMAC-SHA256 con
  `hmac.compare_digest` (tiempo constante); sin cabecera o sin secreto → `False`
  (a diferencia del legacy, que acepta sin firma).
- [x] `domain/channels.py`: `detect_channel` por el campo `object` del envelope
  (`whatsapp_business_account`/`instagram`/`page` → canal; desconocido → `None`).
- [x] `domain/ports.py`: `TenantResolverPort` (levantó `TenantNotFoundError`) y
  `DeduplicationPort.register_once(tenant_id, message_id)`.
- [x] `infrastructure/in_memory.py`: `InMemoryTenantResolver`,
  `InMemoryDeduplication`, `InMemoryChannel` (captura lo enviado).
- [x] Tests: `tests/unit/test_conversation_gateway_domain.py` (24: firma válida/
  alterada/sin cabecera/sin prefijo, detección de 3 canales + desconocido,
  contrato `ChannelMessage` inmutable/con límite 4096/con media, resolución
  presente/ausente/por canal, dedup primera vez/duplicado/aislamiento por tenant,
  conformance de los 3 dobles) + `ChannelPort` en `test_shared_ports.py`.
- [x] Batería verde + commit `feat(paso-9): dominio y channelport del gateway de
  conversacion`.

## Fase 2 — webhook GET/POST  (hecha)

- [x] `application/webhook.py`: `WebhookResponse` + `WebhookReceiver` —
  `verify_subscription` (challenge con `hmac.compare_digest` en tiempo constante;
  cualquier desajuste → 403 genérico sin decir qué falló) y `receive` (firma
  **obligatoria** → `InvalidSignatureError`; JSON defensivo → `ValidationError`;
  `detect_channel` → `EVENT_RECEIVED` o `EVENT_IGNORED`). Con un comentario que marca
  dónde entra el flujo de la Fase 4 (normalize → tenant → dedup → encolado).
- [x] `handler/lambda_webhook.py`: `main` (composition root) sobre el payload 2.0 de
  API Gateway: método GET/POST/405, cabeceras case-insensitive, `rawBody` base64,
  traducción `AppError → statusCode + {"error": <code>}` (nunca `details` ni trazas),
  fail fast si faltan los secretos, `text/plain` para el challenge y
  `application/json` para errores.
- [x] Settings: `CHATBOT_WEBHOOK_VERIFY_TOKEN` + `CHATBOT_META_APP_SECRET`
  (opcionales a nivel de `Settings`; el `WebhookReceiver` exige ambos) con
  `TODO(verify)` de inyección en prod sin exponerlos en el estado de TF.
- [x] Tests: `test_conversation_gateway_webhook.py` (24: challenge ok/5 inválidos,
  firma válida/alterada/ausente/envelope ignorado/cuerpo no-objeto, handler GET/POST
  403/405/base64/fail-fast/sin trazas) + `test_shared_config.py` (1) y
  `test_conversation_gateway_domain.py` (24 de la Fase 1) — **54 tests en verde**.
- [x] Batería verde + commit `feat(paso-9): webhook meta con verificacion y firma`.
- Nota: el `handler = "handler.main"` de Terraform pasará a
  `handler.lambda_webhook.main` al empaquetar el zip (Fase 6).

## Fase 3 — parsers de los 3 canales  (hecha)

- [x] `shared/ports/channel.py`: `normalize_inbound` pasa a devolver
  `list[ChannelMessage]` (Meta agrupa varios mensajes en un evento; `[]` = ignorar)
  y `ChannelMessage` gana `sender_name: str | None` (nombre del perfil de WhatsApp).
- [x] `infrastructure/channels/payload.py`: navegación defensiva del JSON
  (`objeto`/`lista`/`cadena`), `cadena_requerida` y `epoch` (segundos string de
  WhatsApp vs. milisegundos de IG/FB → `datetime` UTC).
- [x] `infrastructure/channels/messaging.py`: envelope `entry[].messaging[]`
  común a IG/FB — descarta estados y ecos, emisor = `recipient.id`, clasifica por
  `attachments[0]` (`file` → `document`, ubicación → `Location: lat, long`) y
  `parse_story_replies` (IG: `story_<id>` + `[Story Reply] …`).
- [x] `infrastructure/channels/whatsapp/parser.py`: recorre todos los
  `entry[].changes[].value`, descarta `statuses`, el eco propio
  (`from == display_phone_number`) y tipos no soportados (`reaction`/
  `interactive` → `TODO(decision)`); tipos text/image/audio/video/document/
  location/sticker con media y caption; fallback de remitente vía
  `contacts[0].wa_id` y `sender_name` del perfil.
- [x] `infrastructure/channels/{messenger,instagram}/parser.py`: envolvente
  compartido; Instagram añade respuestas a historias. Registro `parse_event` en
  `infrastructure/channels/__init__.py` (`_PARSERS` por canal).
- [x] Tests: `tests/contract/test_channel_parsers.py` (30 con
  `pytestmark = pytest.mark.contract`): rutas completas por canal, media
  (caption/URL/filename), estados/eco/no-soportados descartados, multi-mensaje y
  multi-entry, fallback de remitente, errores de payload malformado (sin metadata,
  sin remitente, id/timestamp inválidos) y despacho por registro.
- [x] Batería verde + commit `feat(paso-9): parsers de los 3 canales a channelmessage`.

## Fase 4 — tenant + dedup + encolado  (hecha)

- [x] `shared/contracts/messages.py`: `QueuedMessage(InboundMessage)` con
  `message_type`/`sender_name`/`media_*` y `raw_payload` (cuerpo firmado exacto,
  máx. 200 000); exportado en `shared/contracts/__init__.py`.
- [x] Settings: `CHATBOT_EVENTS_QUEUE_URL`, `CHATBOT_CHANNEL_MAPPING_TABLE`,
  `CHATBOT_PROCESSED_MESSAGES_TABLE` (opcionales en `Settings`; el handler los
  exige al componer, **antes** de crear boto3).
- [x] `domain/ports.py`: `NormalizerPort` (vista de entrada de `ChannelPort`) +
  `DeduplicationPort.release` (rollback si el encolado falla).
- [x] `application/webhook.py`: flujo `firma → parsear → detect_channel →
  normalize → resolver tenant (2 pasos, sin encolado parcial) → dedup +
  encolar`; si el publish falla, `release` de la dedup para no perder el
  reintento de Meta; respuestas `EVENT_RECEIVED`/`EVENT_IGNORED`/
  `EVENT_TENANT_UNKNOWN`; evento duplicado íntegro → `DuplicateMessageError`.
- [x] `infrastructure/dynamodb.py`: `DynamoChannelMapping` (claves exactas del
  legacy `WA_CONFIG#<id>|METADATA`, fallback `store_id`→`tenant_id`,
  `ConsistentRead`) + `DynamoDeduplication` (`MSG_PROCESSED#<id>|DEDUP#<tenant>`,
  `attribute_not_exists(PK)`, TTL 24 h, `release`); errores botocore →
  `ToolError`/`ToolTimeoutError` (condicional → duplicado, no error).
- [x] `adapters/sqs/`: `SQSEventBus(EventBusPort)` — cuerpo `{event, payload}`,
  timeout y errores traducidos con `event_name` en `details` (nunca el payload).
- [x] `handler/lambda_webhook.py`: composición con los 5 settings (fail fast
  antes de crear AWS) y `DuplicateMessageError → 200 EVENT_DUPLICATED`;
  `receptor` inyectable para tests sin AWS.
- [x] Terraform: módulo `infra/modules/sqs/` (cola + DLQ + redrive + SSE/KMS,
  `TODO(verify)` de visibilidad vs. timeout del consumer) y en los 3 entornos:
  tabla `chatbot_processed_messages`, `module "sqs"`, política least-privilege
  de `conversation_gateway` (SendMessage + GetItem del mapeo + Put/Delete de
  dedup) y las 3 env vars de la Lambda; `terraform validate` en verde en los 3.
- [x] Docs: `DATA_MODEL.md` (fila del mapeo corregida a SK `METADATA`/`store_id`
  y nueva fila `chatbot_processed_messages`), `AGENTS.md` del slice (reglas
  2/3/6, tabla y errores) y de `adapters/` (fila `sqs/`), READMEs de
  `infra/modules/sqs` y de los 3 entornos.
- [x] Tests: `test_conversation_gateway_webhook.py` (25, +handler con receptor
  inyectado, duplicado y faltantes de cola/tablas), nuevos
  `test_conversation_gateway_flow.py` (9: feliz, duplicado, parcial, sin mapeo,
  envelope sin encolar, rollback del release, correlación por mensaje) +
  `test_conversation_gateway_dynamodb.py` (15: claves/prefijos/fallback/TTL/
  errores/conformance) + `test_adapters_sqs_event_bus.py` (9) +
  `test_shared_contracts.py` (4 de `QueuedMessage`) — **en verde**.
- [x] Batería verde + commit `feat(paso-9): tenant dedup y encolado del gateway`.

## Criterios de hecho del ROADMAP (§1 fila 9)

- [ ] **Prueba con tráfico real de los 3 canales** → **pendiente de entorno dev**
  (los endpoints de credenciales llegan en la Fase 5; hasta entonces no hay con qué).
- [x] **Deduplicación** (Fase 4, con test de duplicado → 200 silencioso).
- [ ] **Aislamiento por tenant** (Fase 6; la dedup ya es por tenant y hay test
  de no-fuga entre comercios en la Fase 1).
- [ ] Webhook completo tras `ChannelPort`: `hub.challenge`,
  `X-Hub-Signature-256`, resolución de `tenant_id`, SQS (Fases 2–4).
- [ ] Batería completa en verde al cierre de la Fase 7.

## Pendientes explícitos (no bloquean el cierre)

- `TODO(verify)`: valores exactos del campo `object` de Meta (Graph API v24.0); nombres
  exactos de claves IG/FB en el legacy; mecanismo de replicación del mapeo
  canal→tenant desde el legacy; conmutación por número/WABA
  (INTEGRATION_WITH_LEGACY §3); tamaños/timeout de la cola y rate limiting contra
  Meta; empaquetado de los zips de Lambda.
- `TODO(decision)`: si el pipeline nuevo merece un ADR propio (se valora en la Fase 7:
  hoy cubre ADR 0006/0009/0003); respuesta fija al usuario cuando no hay mapeo de
  tenant (imposible sin credenciales del canal → Fase 5). El TTL del dedup quedó
  cerrado en 24 h (heredado del legacy).
