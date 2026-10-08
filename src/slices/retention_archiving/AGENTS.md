# Slice: retention_archiving

> **Fuera de la ruta** (ROADMAP §4). Estado: **definido, sin implementar** (el detalle
> funcional se completa en su paso; este documento es el contrato previo; cierra el
> ADR 0007).

## Responsabilidad
Ciclo de vida de los datos: traslada de lo caliente (DynamoDB con TTL) a archivo en S3
(JSONL por conversación) y elimina, aplicando el mismo plazo a conversaciones, imágenes
y audios. Es el slice que cierra el ADR 0007 y no expone tools al LLM ni participa en
la conversación.

## Entradas y salidas
- Entradas: expiración del TTL en DynamoDB vía Streams, eventos de cambio de política
  por tenant y el plazo configurado por tenant (`../../../docs/architecture/DATA_MODEL.md`).
- Salidas: archivo JSONL en S3 por conversación, purgas con log de auditoría
  (`tenant_id`, volumen, plazo aplicado), métricas en CloudWatch y el contrato de
  política de retención en `../../../shared/contracts/`.

## Ports
- Expone (aplicación a otros slices vía shared/contracts): contrato `RetentionPolicy`
  (plazo por tenant y por tipo de dato; TODO(decision): quién lo publica).
- Consume: `StoragePort` (S3 con lifecycle; adapter `adapters/s3`), `ClockPort` (reloj
  controlable en tests) y los ports del domain que calculan el vencimiento; el
  disparador es DynamoDB Streams.

## Tablas y recursos AWS
| Recurso | Por qué | Paso |
|---|---|---|
| DynamoDB (datos en caliente con TTL) | Vencimiento del plazo por tenant y tipo | fuera de ruta |
| DynamoDB Streams | Archivar antes de que el TTL borre el registro | fuera de ruta |
| S3 (archivo JSONL por conversación + lifecycle) | Archivo duradero y pura final (límite de reglas por bucket: TODO(verify)) | fuera de ruta |
| CloudWatch Logs | Log de cada archivo y de cada purga | fuera de ruta |

## Reglas de negocio clave
1. Nunca se borra sin haber archivado antes, o sin confirmar que no corresponde
   archivar.
2. Mismo plazo para conversaciones, imágenes y audios, configurable por tenant.
3. El archivo es JSONL, un archivo por conversación, con metadatos de tenant y fechas.
4. La pura final la ejecuta el lifecycle de S3; el límite de reglas por bucket es
   TODO(verify).
5. Qué se archiva y qué se borra en definitiva: TODO(decision) (ADR 0007) y se cierra
   fuera de la ruta (ROADMAP §4) con los casos de uso (ver
   `../../../docs/adr/0007-retencion-de-conversaciones-y-media.md`).
6. El Streams entrega al menos una vez: el archivado es idempotente por conversación.
7. Cada purga y cada archivo se registran en log con `tenant_id` y volumen.
8. Este slice NO expone tools al LLM.

## Tools expuestas al LLM
— (no expone tools)

## Errores esperados
| Error | Cuándo ocurre | Cómo se traduce al usuario/log |
|---|---|---|
| `ArchiveFailed` | Falla la escritura del JSONL en S3 | NO se purga; reintento + log error |
| `MissingTenantPolicy` | Tenant sin política de retención | Se aplica el plazo por defecto + log warn |
| `StreamProcessingError` | Error al procesar el Stream | Reintentos y alarma + log error |
| `PurgeWithoutArchive` | Intento de borrar sin archivo previo | Se detiene la purga + log error |

## Cómo probarlo
- `tests/unit/`: con `ClockPort` controlado simulando el paso del plazo → se archiva y
  luego se purga; si el archivo falla → no se borra nada.
- `tests/contract/`: esquema del JSONL por conversación y de `RetentionPolicy`
  (plazo por tenant y tipo de dato).
- `tests/integration/`: TTL expirado → el Stream archiva en S3 y la purga posterior deja
  el registro fuera de DynamoDB (localstack → TODO(verify)).
