# Módulo: dynamodb

Fábrica de tablas operacionales, **una por familia de `DATA_MODEL`** con sufijo
de entorno; on-demand, sin GSI. **Paso 6.**

## Recursos

- `aws_dynamodb_table` por entrada de `tables`: claves `PK`/`SK` (los valores
  llevan los prefijos `ORG#…`/`CONV#…` de DATA_MODEL; ADR 0012), TTL opcional en
  el atributo `ttl` y cifrado SSE con la llave del entorno.
- Entre las tablas, `chatbot_checkpoints` (Paso 8): estado de conversación del
  checkpointer (`DynamoDBMemoryStore`, ADR 0013).

## Variables

| Nombre | Descripción |
| --- | --- |
| `environment` | Sufijo del entorno (`dev`/`staging`/`prod`). |
| `tables` | Mapa: nombre base → `hash_key`, `range_key` opcional, `ttl` bool. |
| `kms_key_arn` | Llave del entorno para cifrado en reposo. |

## Salidas

`table_names` — nombres reales con sufijo (los consume el adapter DynamoDB del
Paso 8).
