# 0006. Reemplazo gradual del backend legacy

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El backend `sahagunonline/back` atiende hoy a la operación real de Sahagún Online:
aproximadamente 35 Lambdas SAM, una DynamoDB single-table, webhook Meta → SQS →
orquestador, y el `ai_chat_service` con Step Functions. Tiene negocio implementado
(citas, pedidos, clientes) que no se va a reescribir desde cero.

ChatBotAws arranca con 3 comercios y un chatbot con 0 usuarios: no puede permitirse
apagar el sistema que ya funciona, ni quedarse sin poder probar el nuevo. Además, la
mayoría de las acciones del chatbot (consultar pedido, agendar cita) son llamadas a
funcionalidad que vive en el legacy.

Hay que elegir cómo conviven los dos sistemas y cómo se va trasladando el tráfico.

## Decisión

Se adopta el **reemplazo gradual, comercio por comercio**, con un webhook Meta propio del
sistema nuevo y las tools de negocio llamando por HTTP al legacy.

Implica:

- **Webhook propio en `conversation_gateway`**: verifica `hub.challenge` para la
  validación de Meta, valida la firma `X-Hub-Signature-256` del payload y envía a **SQS**
  antes de continuar. La verificación de firma es obligatoria y no se puede desactivar en
  ningún entorno.
- **Las tools van a APIs HTTP del legacy** a través del AgentCore Gateway con su Policy
  (ADR 0004): el negocio ya escrito sigue siendo el del legacy mientras dure la
  convivencia.
- **Catálogo replicado** legacy → Aurora para el RAG (ADR 0002): el conocimiento se lee
  del nuevo sistema, el negocio se escribe en el legacy.
- **La migración es por comercio**: se conmuta un `store_id` completo, no un endpoint suelto
  ni un porcentaje de mensajes.
- El mecanismo de conmutación por número/comercio (quién recibe el webhook, hacia dónde
  apunta el enrutado) queda pendiente de definirse con la infraestructura:
  `TODO(verify)`.
- El slice `src/adapters/legacy_backend/` concentra los adaptadores al legacy para que
  solo ese paquete se entere de que el legacy existe.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Reenvío desde el legacy (el webhook viejo sigue mandando y reenvía al nuevo) | No hay que tocar la configuración de Meta; corte de tráfico mínimo. | Acopla los despliegues: el legacy tiene que conocer al nuevo y versionarse con él; un fallo del reenvío no se distingue de un fallo del legacy. | Se descarta porque encadena ambos sistemas y hace el rollback ambiguo. |
| Corte big-bang (todo el tráfico de golpe, apagando el legacy) | Un solo sistema tras el corte; sin doble mantenimiento. | Con 0 usuarios de chatbot no se valida nada y con producción real el riesgo es alto; no hay marcha atrás barata. | Se descarta por riesgo operativo: la reversibilidad es requisito. |
| Prototipo paralelo (chatbot nuevo sin tráfico real) | Cero riesgo para la operación. | No produce valor ni aprendizaje con usuarios reales; tiende a convertirse en un proyecto eterno paralelo. | Se descarta porque no valida nada: se quiere tráfico real desde el primer comercio. |

## Consecuencias

### Positivas

- Cada comercio migra con un conmutador y se puede volver atrás sin reescribir nada.
- El negocio ya probado del legacy se reutiliza en lugar de reimplementarse.
- El aprendizaje llega con el primer comercio y se aplica a los siguientes dos.
- La superficie que conoce al legacy queda aislada en `legacy_backend`.

### Negativas / riesgos

- **Convivencia temporal**: dos sistemas en paralelo durante la fase de migración.
- **Doble mantenimiento limitado**: un fix de negocio puede que tenga que aplicarse en
  legacy y en el nuevo lado (o solo en el legacy, vía tool); hay que acotarlo y
  documentarlo.
- Los datos viven repartidos: conversaciones en el nuevo, negocio en el legacy. La
  consistencia entre ambos es eventual (ADR 0002).
- El mecanismo de conmutación por número aún no está cerrado: `TODO(verify)`.
- Riesgo de que la convivencia se alargue indefinidamente si no se fija qué comercio
  migra en cada fase.

## Relacionados

- [0002. Reparto de datos: Aurora, DynamoDB y S3](0002-reparto-de-datos-aurora-dynamodb-s3.md)
- [0003. Multi-tenancy: tenant resuelto en el gateway](0003-multi-tenancy-tenant-en-gateway.md)
- [0004. Orquestación: LangGraph, Bedrock y AgentCore modular](0004-orquestacion-langgraph-agentcore-modular.md)
- [0009. ChannelPort único para los canales Meta](0009-channelport-unico-canales-meta.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
