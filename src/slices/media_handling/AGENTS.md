# Slice: media_handling

> **Fuera de la ruta** (ROADMAP §4). Estado: **definido, sin implementar** (el detalle
> funcional se completa en su paso; este documento es el contrato previo).

## Responsabilidad
Gestión de imágenes y audios: descarga el medio del webhook de Meta por su ID temporal,
lo guarda en S3 con prefijo `tenant_id/...`, transcribe los audios para que el texto
entre en el pipeline normal y envía los medios de respuesta tras `ChannelPort`. No
decide intención ni aplica la retención (eso es `retention_archiving`, mismo plazo según
el ADR 0007).

## Entradas y salidas
- Entradas: webhook de `conversation_gateway` con el `media_id` temporal de Meta, ya con
  `tenant_id` y `correlation_id`; solicitudes de envío de medio desde los especialistas.
- Salidas: objeto en S3 bajo `tenant_id/...`, texto transcrito que se inyecta al turno,
  medio enviado por el canal y logs de auditoría sin binarios ni PII.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): `MediaIngested` y
  `TranscriptReady` (TODO(decision): nombres finales).
- Consume: `StoragePort` (adapter `adapters/s3`), `TranscriptionPort` (Amazon
  Transcribe; adapter nuevo en `adapters/` → TODO(verify) si se reutiliza la capacidad
  del legacy), `ChannelPort` (tres canales Meta, ADR 0009) y `ClockPort`.

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| S3 (prefijo `tenant_id/...`) | Almacenamiento del medio con aislamiento por tenant | fuera de ruta |
| Amazon Transcribe | Transcripción de audio (¿capacidad del legacy? TODO(verify)) | fuera de ruta |
| CloudWatch Logs | Descargas, reintentos y fallos con `correlation_id` | fuera de ruta |

## Reglas de negocio clave
1. La clave S3 siempre se deriva del `tenant_id` del contexto, nunca del payload del
   LLM.
2. Audio → transcripción → el texto entra al mismo pipeline de conversación.
3. El medio aplica el MISMO plazo de retención que las conversaciones (ADR 0007, ver
   `../../../docs/adr/0007-retencion-de-conversaciones-y-media.md`).
4. El ID de Meta es de corta duración: se descarga en cuanto llega; el comportamiento
   exacto de expiración es TODO(verify).
5. Tipo no soportado → se responde sin el medio; la conversación no se rompe.
6. Descarga fallida → retry acotado + log error; nunca se propaga al usuario.
7. No se loguean binarios ni PII del medio.

## Tools expuestas al LLM
— (no expone tools)

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `MediaExpired` | El ID de Meta ya expiró | Pedir el medio de nuevo + log warn |
| `UnsupportedMediaType` | Tipo distinto de imagen o audio | Se ignora el medio + log info |
| `DownloadFailed` | Meta no entrega el archivo tras los reintentos | El turno continúa sin medio + log error |
| `TranscriptionFailed` | Transcribe falla | Se le pide escribir el texto + log warn |
| `TenantMismatch` | El medio pertenece a otro tenant | Rechazo genérico + log error |

## Cómo probarlo
- `tests/contract/`: esquema del webhook con media (`media_id`, tipo, URL) y contrato
  `MediaIngested` con `tenant_id` obligatorio.
- `tests/unit/`: clave S3 por tenant (`Sede_Elite_01/...`) imposible de manipular desde
  el payload, y rechazo de tipos no soportados.
- `tests/agent_evals/datasets/`: audio recibido → transcripción disponible en el turno;
  medio expirado → la conversación continúa sin él.
