# Architecture Decision Records

Los ADR (Architecture Decision Records) son documentos cortos que registran una decisión
arquitectónica junto con su contexto, las alternativas que se valoraron y sus consecuencias.
En este repositorio viven en `docs/adr/` y son la fuente de verdad de por qué el sistema
está construido como está.

## Cómo se usan

### Estados

| Estado | Significado |
| --- | --- |
| **Aceptado** | La decisión se tomó y se aplica. Solo cambia si se deroga con un ADR nuevo que la sustituya. |
| **Pendiente** | El marco y las opciones están documentados, pero falta información para cerrarla. Los huecos se marcan con `TODO(decision)`. |
| **Obsoleto** | La decisión fue sustituida. Se conserva el documento y se indica qué ADR la reemplaza. |

### Cuándo crear uno

- Cuando se elige entre dos o más alternativas con impacto estructural (repositorio,
  despliegue, modelo de datos, seguridad, coste).
- Cuando una decisión condiciona trabajos futuros de más de una tarea o de otra fase.
- Cuando se aplaza una decisión pero hace falta dejar constancia del marco y de las
  preguntas abiertas: se crea con estado **Pendiente**.

No se crea un ADR para elecciones locales ya cubiertas por convención (nombres de archivo,
formato de log, estilo de tipos).

### Quién aprueba

El **Arquitecto de la plataforma ChatBotAws** propone y aprueba. Cualquier persona del
puede sugerir un ADR o una modificación mediante revisión de código; una vez fusionado,
el ADR es vinculante para el resto de la fase. Para derogar o reemplazar un ADR se
escribe un ADR nuevo y se marca el antiguo como **Obsoleto**.

## Plantilla

Cada ADR de este directorio copia literalmente esta plantilla. El identificador `NNNN`
es correlativo y el nombre del archivo es `NNNN-titulo-en-ingles.md`.

````markdown
# NNNN. <Título>

- **Estado:** Aceptado | Pendiente
- **Fecha:** YYYY-MM-DD
- **Decisores:** <rol o persona>

## Contexto
<qué problema o fuerza obliga a decidir, con datos concretos del proyecto>

## Decisión
<la decisión en prosa + lista explícita de qué implica>

## Alternativas consideradas
<table: Alternativa | Ventajas | Desventajas | Por qué se descartó>

## Consecuencias
### Positivas
### Negativas / riesgos

## Relacionados
<enlaces a otros ADRs y docs relevantes>
````

Reglas complementarias:

- Documentación en **español**; identificadores, rutas y nombres de servicios en **inglés**.
- Enlaces **relativos** entre documentos (`../architecture/OVERVIEW.md`, `../../AGENTS.md`).
- Nunca se inventan APIs, parámetros ni precios de AWS: se marca `TODO(verify)` o
  `TODO(verify pricing)` hasta confirmarlo.
- Sin secretos y sin emojis.

## Índice

| # | Título | Estado | Fecha |
| --- | --- | --- | --- |
| 0001 | [Arquitectura hexagonal y vertical slicing](0001-arquitectura-hexagonal-y-vertical-slicing.md) | Aceptado | 2026-10-07 |
| 0002 | [Reparto de datos: Aurora, DynamoDB y S3](0002-reparto-de-datos-aurora-dynamodb-s3.md) | Aceptado | 2026-10-07 |
| 0003 | [Multi-tenancy: tenant resuelto en el gateway](0003-multi-tenancy-tenant-en-gateway.md) | Aceptado | 2026-10-07 |
| 0004 | [Orquestación: LangGraph, Bedrock y AgentCore modular](0004-orquestacion-langgraph-agentcore-modular.md) | Aceptado | 2026-10-07 |
| 0005 | [Comunicación entre slices vía contracts](0005-comunicacion-entre-slices-via-contracts.md) | Aceptado | 2026-10-07 |
| 0006 | [Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md) | Aceptado | 2026-10-07 |
| 0007 | [Retención de conversaciones y media](0007-retencion-de-conversaciones-y-media.md) | Pendiente | 2026-10-07 |
| 0008 | [Contextual grounding en el chatbot](0008-contextual-grounding-en-chatbot.md) | Aceptado | 2026-10-07 |
| 0009 | [ChannelPort único para los canales Meta](0009-channelport-unico-canales-meta.md) | Aceptado | 2026-10-07 |
| 0010 | [Composición de grafos por invocación](0010-composicion-de-grafos-por-invocacion.md) | Aceptado | 2026-10-08 |
| 0011 | [Confirmación por política con drafts](0011-confirmacion-por-politica-con-drafts.md) | Aceptado | 2026-10-09 |
