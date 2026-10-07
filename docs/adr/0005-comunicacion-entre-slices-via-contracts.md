# 0005. Comunicación entre slices vía contracts

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

Con 13 slices verticales (ADR 0001) aparece de inmediato el problema de fondo del
slicing: los slices se necesitan entre sí. `sentiment_handoff` necesita el resultado del
turno que generó `supervisor`; `orders` necesita el perfil que guarda `customer_context`;
`media_handling` entrega un archivo que después archiva `retention_archiving`.

Si cada slice importa libremente el módulo de otro, en pocas semanas se reconstruye el
acoplamiento del legacy con mejoras de nombres de carpetas. Y si en cambio cada slice
accede directamente a las tablas de otro, el reparto de datos (ADR 0002) se rompe. Hace
falta una forma única, versionable, de que un slice consuma lo que otro expone.

## Decisión

La comunicación entre slices se hace **exclusivamente a través de contratos declarados en
`src/shared/contracts/`**, escritos como modelos **Pydantic**.

Implica:

- Cada dato que cruza frontera de slice tiene un modelo Pydantic en
  `src/shared/contracts/`, con campos, tipos, validación y versión explícita.
- Un slice **importa contratos, nunca el código de otro slice**. Los contratos son la
  superficie pública; todo lo demás es interno.
- Los contratos se versionan: añadir un campo opcional es compatible; cambiar el sentido
  de un campo obliga a versión nueva y a actualizar a los consumidores en el mismo PR.
- La regla se hace efectiva con **import-linter y un test de arquitectura en CI** que
  **prohíbe los imports cruzados entre `src/slices/*`** y falla el pipeline si aparecen.
- `src/shared/ports/` define las interfaces (puertos) que un contrato necesita y que el
  slice receptor implementa en su `infrastructure/` (ADR 0001).
- Las llamadas síncronas dentro del grafo usan contratos; la persistencia del intercambio
  se hace en DynamoDB con las claves definidas por el slice dueño de los datos.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Imports directos entre slices (`from slices.orders.domain import Order`) | Cero fricción inicial; tipado completo en el editor. | Cualquier cambio interno rompe a otros slices; el grafo de dependencias se vuelve imposible de visualizar; reproduciría el acoplamiento del legacy. | Se descarta por acoplamiento: es exactamente lo que el slicing busca evitar. |
| Eventos vía SNS/SQS directamente entre slices | Desacople real; natural para handoff y media asíncronos. | Complica el seguimiento de un turno (trazas repartidas); orden y reintentos a gestionar; sobre-operatorio con 3 comercios. | No se descarta para el futuro: queda anotado como posible evolución para los flujos ya asíncronos, y exigiría ADR nuevo. |
| Canal compartido en DynamoDB (una tabla que todos leen/escriben) | Desacople y despliegue independiente. | Sin contrato tipado: cada lector interpreta el payload a su manera; hay que resolver concurrencia y compatibilidad a mano. | Se descarta porque la semántica queda implícita, que es el fallo típico de la single-table del legacy. |

## Consecuencias

### Positivas

- La superficie pública de cada slice es un conjunto pequeño, legible y versionado de
  modelos Pydantic.
- Romper a un consumidor se ve en la revisión del contrato, no en producción.
- El test de imports cruzados convierte la arquitectura en una garantía del pipeline,
  no en una convención.
- Refactorizar el interior de un slice no obliga a tocar a nadie más si el contrato
  no cambia.

### Negativas / riesgos

- Más ceremony que un import directo: para un dato de dos campos hay que crear un modelo
  y mantenerlo.
- Las versiones de contrato pueden acumularse si no se retiran las obsoletas.
- El contrato puede convertirse en el "least common denominator" si se diseñan modelos
  demasiado genéricos; conviene diseñarlos desde el caso de uso.
- Un único archivo de contracts compartido es un punto de conflicto en PR concurrentes.

## Relacionados

- [0001. Arquitectura hexagonal y vertical slicing](0001-arquitectura-hexagonal-y-vertical-slicing.md)
- [0002. Reparto de datos: Aurora, DynamoDB y S3](0002-reparto-de-datos-aurora-dynamodb-s3.md)
- [0003. Multi-tenancy: tenant resuelto en el gateway](0003-multi-tenancy-tenant-en-gateway.md)
- [0009. ChannelPort único para los canales Meta](0009-channelport-unico-canales-meta.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
