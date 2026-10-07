# 0002. Reparto de datos: Aurora, DynamoDB y S3

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El sistema necesita almacenar tres clases de datos con requisitos opuestos:

- **Conocimiento**: el catálogo y la documentación de cada comercio, troceados y
  embebidos para recuperación vectorial (RAG). Requiere búsqueda semántica, filtros por
  metadatos y consultas relacionales. Se replica desde el backend legacy.
- **Operacional**: sesiones, mensajes en caliente, estado de handoff, contadores de
  abuso. Se escribe y se lee en cada turno de chat; necesita baja latencia, escalado
  automático y caducidad automática (TTL) para no acumular datos que ya no sirven.
- **Archivo**: media recibida por WhatsApp/Instagram/Messenger (imágenes, audio,
  documentos) y copias históricas. Es binario, de tamaño variable y su coste debe bajar
  con el tiempo (lifecycle), no se consulta por transacción.

El legacy concentra casi todo en una DynamoDB single-table y funciona, pero no resuelve
el RAG: no hay ni SQL ni índices vectoriales. Aurora PostgreSQL Serverless v2 con
pgvector ya está decidida para conocimiento, y hay que fijar qué va a cada sitio para no
repartir los datos por costumbre.

## Decisión

Se reparten los datos por tipo de acceso, no por origen:

- **Aurora PostgreSQL Serverless v2 + pgvector → solo conocimiento**: catálogo
  replicado desde el legacy, documentos y sus embeddings, metadatos de chunks, filtros
  por `tenant_id`.
- **DynamoDB → operacional**: conversaciones y sesiones en caliente, estado de turno,
  con TTL por registro y Streams para el pipeline de retención.
- **S3 → archivo**: media entrante y salidas archivadas, con lifecycle que mueve a
  clases de almacenamiento más baratas y finalmente borra.

Implica:

- El catálogo se **replica** legacy → Aurora: es una copia derivada, no la fuente de
  verdad; la fuente sigue en el legacy mientras convivan (ver ADR 0006).
- El LLM nunca toca ninguna base de datos directamente: solo recibe el resultado de las
  tools (ver ADR 0004 y ADR 0008).
- Cada slice declara en su capa `infrastructure/` a qué almacén habla; no hay acceso
  cruzado a almacenes de otros slices.
- Cada almacén tiene una razón de existir escrita en este ADR; añadir un cuarto exige un
  ADR nuevo.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Todo en DynamoDB single-table, como el legacy | Un solo sistema que operar; patrón ya probado en Sahagún Online. | Sin SQL ni búsqueda vectorial: el RAG tendría que reconstruirse fuera; las consultas ad-hoc de negocio son incómodas. | El requisito de RAG con pgvector es el que fuerza la separación; se descarta por no dar soporte al conocimiento. |
| Conocimiento también en DynamoDB, con embeddings como atributos | Cero servicios nuevos; todo junto con lo operacional. | Búsqueda vectorial y joins con metadatos no encajan en el modelo; filtrado por tenant y por categoría se vuelve código frágil y caro. | Se descarta por coste de implementación y por degradar la calidad de la recuperación. |
| Un único S3 como almacén de todo ("data lake") | Coste de almacenamiento mínimo; esquema libre. | Lecturas/escrituras por mensaje de chat con latencia insuficiente; sin transacciones ni índices; todo el acceso pasa por código propio. | Se descarta por latencia y por obligar a reimplementar lo que Aurora y DynamoDB ya dan. |

## Consecuencias

### Positivas

- Cada almacén se usa para lo que hace bien: SQL + vector en Aurora, TTL y baja latencia
  en DynamoDB, lifecycle barato en S3.
- La réplica de catálogo permite tocar el RAG sin tocar el legacy ni afectar a sus tablas.
- El borrado y la retención son aplicables por almacén con sus propios mecanismos
  (TTL/Streams en DynamoDB, lifecycle en S3; ver ADR 0007).
- Aislar el conocimiento evita que una carga de indexación perjudique al chat en vivo.

### Negativas / riesgos

- Tres sistemas que hay que desplegar, monitorizar y pagar en lugar de uno.
- La réplica del catálogo introduce **consistencia eventual**: un cambio de precio en el
  legacy no está en Aurora hasta la siguiente sincronización; hay que definir la
  frecuencia y el detectable de desfase `TODO(verify)`.
- Aurora Serverless v2 tiene un coste fijo aunque nadie consulte el RAG
  (`TODO(verify pricing)`).
- Riesgo de fuga de datos operacionales a Aurora por comodidad, rompiendo la regla de
  este ADR: lo controla la revisión de código y el test de arquitectura (ADR 0001).

## Relacionados

- [0001. Arquitectura hexagonal y vertical slicing](0001-arquitectura-hexagonal-y-vertical-slicing.md)
- [0004. Orquestación: LangGraph, Bedrock y AgentCore modular](0004-orquestacion-langgraph-agentcore-modular.md)
- [0006. Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md)
- [0007. Retención de conversaciones y media](0007-retencion-de-conversaciones-y-media.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
