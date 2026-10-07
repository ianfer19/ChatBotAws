# 0007. Retención de conversaciones y media

- **Estado:** Pendiente
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

Cada turno de chat deja tres rastros: el **texto de la conversación** (operacional, en
DynamoDB), los **archivos media** entrantes y salientes (imágenes, audio, documentos, en
S3) y las **trazas de orquestación** (logs con `correlation_id`). El slice
`retention_archiving` existe precisamente para gestionar su ciclo de vida.

No se puede decidir todavía un plazo concreto porque faltan los casos de uso reales de la
Fase 7 (qué consulta legal aplica, qué pide cada comercio, qué necesita soporte para
revisar una conversación). Lo que sí hay que fijar ahora es el **marco** en el que se
tomará la decisión, para que el diseño de almacenamiento (ADR 0002) ya lo soporte.

## Decisión

Se adopta un **marco de tres estados** para conversaciones y media, con **el mismo plazo
aplicado a ambos** para no tener dos políticas que diverjan:

- **Hot**: datos vivos en DynamoDB (conversación, índice de media) y media accesible en
  S3. Es donde se lee durante la operación.
- **Archivado**: pasado el plazo, la conversación se copia a S3 en forma compacta (JSON
  por sesión o por rango) y el registro hot se elimina; el media sigue con su lifecycle.
- **Borrado**: pasado el plazo máximo, se elimina el archivo archivado también.

Implica:

- **TTL de DynamoDB** sobre los registros de conversación para el paso hot → fuera, con
  **DynamoDB Streams** para que `retention_archiving` archive antes de que el TTL borre
  definitivamente (el TTL solo elimina, no copia).
- **Lifecycle de S3** sobre las claves de media y de archivo para el paso archivado →
  borrado. El límite de reglas de lifecycle aplicables a un bucket está por confirmar:
  `TODO(verify)`.
- El plazo es **igual para conversaciones y para media**: un único valor de política.
- El diseño del slice admite que el plazo sea **configurable por tenant**, aunque la
  decisión de si lo es, se cierra en la Fase 7.

### Opciones abiertas (`TODO(decision)`)

- ¿Qué se archiva y qué se borra definitivamente? Concretamente: ¿se archiva el texto y
  se borra el media, o ambos se archivan y ambos se borran?
- ¿Un plazo único para todos los comercios o plazo por tenant configurable con un
  máximo legal común?
- ¿Qué dice el marco legal colombiano (Ley 1581 de protección de datos) sobre plazos
  mínimos y derechos del titular? Requiere revisión jurídica: `TODO(verify)`.

La decisión se cierra en la **Fase 7**, con los casos de uso sobre la mesa →
`TODO(decision)`.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Todo en DynamoDB con TTL (sin archivo) | Mecanismo de un solo paso, cero código de archivado. | La conversación desaparece sin copia: soporte no puede revisar nada; el media en S3 quedaría huérfano. | Se descarta porque elimina la posibilidad de auditoría y de soporte. |
| Conservarlo todo indefinidamente en S3 (data lake) | Máxima información disponible para futuros análisis. | Coste creciente y sin límite; incumple el derecho de supresión del titular. | Se descarta por coste y por obligaciones de protección de datos. |
| Plazo distinto para texto y para media | Optimiza cada tipo por su coste y sensibilidad. | Dos políticas que divergen, más casos de prueba y más decisiones abiertas. | Se descarta de momento por complejidad; puede reabrirse en la Fase 7 si los casos de uso lo exigen. |

## Consecuencias

### Positivas

- El almacenamiento ya está diseñado (ADR 0002) con TTL y lifecycle listos: cuando se
  cierre el plazo no habrá que rediseñar tablas ni buckets.
- Un solo plazo para texto y media simplifica comunicarlo a los comercios y auditarlo.
- El marco hot → archivado → borrado permite responder a una solicitud de soporte
  durante la ventana caliente y cumplir la supresión después.

### Negativas / riesgos

- Con el ADR pendiente, cualquier implementación prematura de retención puede quedar
  inutilizada; conviene no programar plazos fijos hasta la Fase 7.
- El pipeline Stream → archivado → S3 es una pieza asíncrona que puede perder eventos o
  reordenarlos: hay que diseñarlo idempotente.
- Si el marco legal exige un plazo mínimo mayor que el operativo, habrá que retrasar el
  borrado y rehacer el lifecycle.
- Un lifecycle con muchas reglas por prefijo puede no bastar: `TODO(verify)`.

## Relacionados

- [0002. Reparto de datos: Aurora, DynamoDB y S3](0002-reparto-de-datos-aurora-dynamodb-s3.md)
- [0004. Orquestación: LangGraph, Bedrock y AgentCore modular](0004-orquestacion-langgraph-agentcore-modular.md)
- [0008. Contextual grounding en el chatbot](0008-contextual-grounding-en-chatbot.md)
- [Índice de ADRs](README.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
