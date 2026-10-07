# Retención y borrado de datos

Documento de la Fase 1 (esqueleto). Qué datos genera ChatBotAws, dónde viven, y el marco
propuesto de **hot → archivo → eliminación**. La decisión de plazos está **pendiente**
([ADR 0007](../adr/0007-retencion-de-conversaciones-y-media.md), estado Pendiente) y se
cierra en la Fase 7 con los casos de uso reales. Todo dato de AWS no confirmado aparece
como `TODO(verify)`; los huecos de decisión, como `TODO(decision)`.

Ver también: [../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md),
[SECURITY.md](./SECURITY.md), [THREAT_MODEL.md](./THREAT_MODEL.md),
[../adr/README.md](../adr/README.md), [`../../AGENTS.md`](../../AGENTS.md).

## 1. Estado de la decisión

| Campo | Valor |
|---|---|
| ADR | [0007 — Retención de conversaciones y media](../adr/0007-retencion-de-conversaciones-y-media.md) |
| Estado | **Pendiente** |
| Cuándo se cierra | Fase 7, con los casos de uso (slice `retention_archiving`) |
| Qué falta decidir | `TODO(decision)`: qué se archiva y qué se borra; plazo por tenant configurable; si el archivo se guarda "caliente" o solo en S3 Glacier-equivalente → `TODO(verify)` (clases de almacenamiento) |

Este documento describe el **marco** y las restricciones que ya están fijadas. No fija
plazos: cualquier número que aparezca aquí es una propuesta, no una obligación.

## 2. Datos que produce el sistema y dónde viven

| Dato | Almacén | Notas |
|---|---|---|
| Conversaciones (mensajes, estado de turno) | DynamoDB (operacional, con TTL) → S3 (archivo) | Checkpointer de LangGraph + historial |
| Media (imágenes y audios) | S3 | Bajo `/<tenant_id>/...`; su plazo debe ser **igual** al de la conversación (sección 4) |
| Contexto de cliente | DynamoDB | Preferencias, datos de contacto del comercio |
| Memoria entre sesiones | AgentCore Memory | Resumen y hechos estables; no es fuente de verdad operacional |
| Conocimiento (chunks + embeddings) | Aurora PostgreSQL + pgvector | Solo conocimiento del comercio; no es dato de conversación |
| Logs de aplicación | CloudWatch Logs | JSON con `tenant_id` y `correlation_id` |
| Auditoría de tools y de bloqueos | DynamoDB | Quién invocó qué, con qué resultado; motivos de bloqueo |
| Configuración y prompts por tenant | Bedrock Prompt Management + `prompts/` | Versionado, no caduca por retención |

El detalle de claves, particiones y rutas está en
[../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md).

## 3. Marco propuesto: hot → archivo → eliminación

```text
  HOT (consultado en conversación)          ARCHIVO (consulta rara)        ELIMINACIÓN
  -----------------------------            ------------------------       ---------------
  DynamoDB con TTL  ------------------->   S3 bajo prefijo del tenant ---> borrado
  (conversación reciente, contexto,        (conversaciones y media        (fin de plazo;
   auditoría)                               de conversaciones cerradas)    sin copias sueltas)
```

1. **Hot**: mientras la conversación está viva y durante el plazo caliente, los datos
   consultables están en DynamoDB. El TTL marca cuándo deja de estar "caliente".
2. **Archivo**: antes de que el TTL borre, un consumidor de DynamoDB Streams copia lo que
   haya que conservar a S3, con la **misma fecha de vida** que el dato original.
3. **Eliminación**: al llegar el plazo, se borra el objeto archivado (lifecycle de S3) y no
   quedan copias en otros almacenes. El borrado es el estado final, no una excepción.

Las tres etapas usan el **mismo plazo por tenant**: no se puede conservar la imagen de una
conversación que ya se borró.

## 4. Requisito: mismo plazo para conversaciones, imágenes y audios

- Conversación, imagen y audio de un mismo intercambio comparten fecha de referencia y
  plazo. Es un requisito del diseño, no una preferencia: si se archiva el texto, se archiva
  la media asociada; si se borra el texto, se borra la media.
- El plazo es **configurable por tenant** (`TODO(decision)`: quién lo configura y con qué
  valores por defecto), pero la igualdad conversación/media es indivisible.
- Si un día se pide un plazo distinto para media, se abre un ADR nuevo; no se hace "por
  ajuste de lifecycle".

## 5. TTL de DynamoDB

- **Cómo funciona**: el TTL se configura por tabla, sobre un atributo con fecha/hora; cuando
  ese instante pasa, el elemento se elimina de la tabla. Elementos sin
  valor en el atributo no caducan nunca → todo lo que debe caducar lleva el atributo, y hay
  un test que falla si un ítem escribible no lo trae.
- **Antes de borrar hay que archivar**: el borrado por TTL es definitivo, así que la
  conservación se hace con **DynamoDB Streams**: un Lambda consume los eventos de la tabla y
  copia a S3 lo que corresponda (conversaciones cerradas) antes de que desaparezca. Si el
  Stream falla, el dato no se archiva y se pierde → la cola y los reintentos forman parte
  del diseño de `retention_archiving` (Fase 7) → `TODO(verify)` (número máximo de streams y
  política de reintento de la tabla).
- Auditoría y bloqueos: para conservarlos más allá del plazo caliente, se archivan igual y
  se borran con el mismo plazo (`TODO(decision)` si la auditoría necesita un plazo propio).

## 6. Lifecycle de S3

- Reglas de lifecycle **por prefijo de tenant** (`/<tenant_id>/...`) para que cada comercio
  pueda tener su plazo sin reglas globales que toquen a todos.
- Una regla por prefijo y transición: pasar a la clase de archivo durante la vida útil y
  **borrar** al final. Transiciones y clases concretas → `TODO(verify)` (clases y tiempos
  mínimos de permanencia).
- **Límite de reglas de lifecycle por bucket** → `TODO(verify)`: si el límite es bajo, la
  alternativa es agrupar por plazo común (misma vida útil → mismo prefijo) y no crear una
  regla por tenant. Se decide en la Fase 7 antes de escribir las reglas.
- El bucket de media y el de archivo de conversaciones aplican el mismo plazo por tenant
  (sección 4).

## 7. AgentCore Memory y logs de CloudWatch

| Almacén | Qué pasa en el marco | Estado |
|---|---|---|
| AgentCore Memory | Sus políticas de retención se alinean con D6/ADR 0007: si la conversación se borra, el resumen que la resume también | `TODO(verify)` (cómo se purga Memory por tenant/sesión) y `TODO(decision)` (plazo) |
| CloudWatch Logs | Retención de log groups con el mismo marco de plazos; los logs contienen `tenant_id` y `correlation_id` | Retención de logs → `TODO(verify)` (opciones y máximo); plazo → `TODO(decision)` |
| DynamoDB Streams | No es un almacén de destino: es el mecanismo de "archivar antes de borrar" | Definido en la Fase 7 |
| Aurora (conocimiento) | **No aplica** el plazo de conversaciones: es material del comercio, no datos de clientes en conversación | Su ciclo de vida lo gobierna el catálogo (`TODO(decision)` si se pide borrado de un chunk) |

## 8. Decisiones pendientes

- `TODO(decision)` **Qué se archiva y qué se borra directamente**: ¿todo el historial o
  solo resúmenes? ¿Se archiva la media o solo su metadato?
- `TODO(decision)` **Plazo por tenant configurable**: rango permitido, quién lo pone
  (¿el comercio? ¿nuestro operador?) y valor por defecto.
- `TODO(decision)` **Plazo de auditoría y de logs** frente al plazo de conversaciones.
- `TODO(verify)` **Marco legal colombiano** (Ley 1581 de 2012 / hábeas data): plazos de
  conservación, obligaciones del responsable del tratamiento y qué exige para el derecho de
  supresión. Nada de este documento afirma una obligación legal hasta verificarlo.
- `TODO(decision)` **Relación con el legacy**: los datos que siguen en `sahagunonline/back`
  no los borra este sistema; se coordina con el comercio (ver
  [../architecture/OVERVIEW.md](../architecture/OVERVIEW.md)).

## 9. Derecho de supresión del cliente final

Flujo previsto cuando un cliente pide borrar sus datos:

```text
1. Solicitud      El cliente escribe su pedido de supresión por el canal
                  (o el comercio la recibe por su propio soporte)
        v
2. Comercio       El comercio la valida y confirma a quién aplica
                  (identidad del cliente, alcance: un tenant o todos)
        v
3. Orquestación   Se registra la solicitud con correlation_id y tenant_id
                  (retention_archiving, Fase 7)
        v
4. Borrado        Se ejecuta en TODOS los almacenes: DynamoDB (conversación,
                  contexto, auditoría), S3 (archivo y media), AgentCore Memory;
                  logs de CloudWatch según el plazo decidido
        v
5. Evidencia      Se deja constancia del borrado (qué, cuándo, por quién)
                  sin conservar el contenido borrado
```

- Alcance y plazo de respuesta del responsable/titular → `TODO(verify)` (marco legal, sección 8).
- El borrado no puede dejar huérfanos: si un dato se copió, el flujo lo cubre o el flujo
  está incompleto.
- El legacy conserva sus propios datos mientras viva: la supresión aquí no la borra allí →
  `TODO(decision)` (coordinación con `sahagunonline/back`).

## 10. Tabla resumen

| Dato | Almacén | Retención actual | Retención propuesta | Estado |
|---|---|---|---|---|
| Conversaciones (hot) | DynamoDB | Sin plazo fijado (TTL sin valor) | TTL con plazo por tenant | Pendiente (ADR 0007) |
| Conversaciones (archivo) | S3 | Sin lifecycle | Mismo plazo que hot, luego borrado | Pendiente (ADR 0007) |
| Imágenes y audios | S3 | Sin lifecycle | **Igual** que la conversación asociada | Pendiente (ADR 0007) |
| Contexto de cliente | DynamoDB | Sin plazo | Igual que la conversación del tenant | Pendiente (ADR 0007) |
| Memoria AgentCore | AgentCore Memory | Sin plazo | Alineada con ADR 0007 | `TODO(verify)` purga por tenant |
| Auditoría de tools y bloqueos | DynamoDB | Sin plazo | `TODO(decision)` (¿plazo propio?) | Pendiente |
| Logs de aplicación | CloudWatch Logs | Retención de log group → `TODO(verify)` | `TODO(decision)`, coherente con auditoría | Pendiente |
| Conocimiento (chunks) | Aurora + pgvector | Sin plazo | Ciclo de catálogo, no de conversación | `TODO(decision)` |
| Prompts versionados | Prompt Management + `prompts/` | Versionado, sin borrado | Conservar versiones para auditoría | Propuesto |

## 11. Cómo se cierra este documento

1. Fase 7: casos de uso reales (¿qué consulta el comercio después de 30/90/180 días?).
2. Verificar plazos legales y técnicos (`TODO(verify)` de las secciones 6, 7 y 8).
3. Cerrar el [ADR 0007](../adr/0007-retencion-de-conversaciones-y-media.md) con la decisión
   y convertir las propuestas de la tabla resumen en valores configurados.
4. Implementar `retention_archiving` con tests de que "borrado" significa borrado en todos
   los almacenes.

## 12. Referencias

- [../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md) — dónde vive cada dato.
- [../adr/0007-retencion-de-conversaciones-y-media.md](../adr/0007-retencion-de-conversaciones-y-media.md) — ADR en curso.
- [THREAT_MODEL.md](./THREAT_MODEL.md) — activos y consecuencia de su fuga.
- [SECURITY.md](./SECURITY.md) — cifrado, secrets y checklist de publicación.
- [`../../AGENTS.md`](../../AGENTS.md) — convenciones del repo.
