# 0001. Arquitectura hexagonal y vertical slicing

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El backend legado `sahagunonline/back` es un monolito SAM de aproximadamente 35 Lambdas
organizadas por tipo de artefacto (`handlers/`, `services/`, capas compartidas) sobre una
DynamoDB single-table. En esa estructura una sola feature de negocio —por ejemplo, crear
una cita— está repartida entre varios servicios, varios handlers y varias tablas, de modo
que entenderla o cambiarla exige recorrer casi todo el repositorio. La deuda acumulada es
uno de los motivos del proyecto nuevo.

ChatBotAws nace con 13 slices (`conversation_gateway`, `orders`, `appointments`,
`knowledge_rag`, `customer_context`, `media_handling`, `sentiment_handoff`,
`abuse_protection`, `supervisor`, `retention_archiving`, `tenant_prompts`, entre otros),
más una capa `adapters/` de adaptadores AWS y una capa `shared/` transversal. El volumen
inicial son 3 comercios y un chatbot con 0 usuarios, pero la estructura debe aguantar el
crecimiento sin reescribirse. Hay que decidir cómo se organiza el código y cómo se evita
que los slices se coman entre sí.

## Decisión

Se adopta **arquitectura hexagonal (puertos y adaptadores) aplicada dentro de cada slice**,
combinada con **slicing vertical**: la unidad de organización es la feature de negocio
completa, no la capa técnica.

Implica:

- Cada feature vive en `src/slices/<slice>/` con cuatro subcarpetas: `domain/` (reglas y
  tipos puros, sin I/O), `application/` (casos de uso), `infrastructure/` (adaptadores
  concretos: DynamoDB, Aurora, S3, HTTP al legacy) y `handler/` (punto de entrada Lambda).
- `src/shared/` contiene solo código transversal: `config/`, `context/`, `contracts/`,
  `errors/`, `logging/`, `ports/`.
- `src/adapters/` contiene los adaptadores a servicios AWS reutilizables: `aurora/`,
  `dynamodb/`, `s3/`, `bedrock/`, `agentcore/`, `comprehend/`, `legacy_backend/`.
- Regla de dependencia: `domain` no importa de `application` ni de `infrastructure`;
  `infrastructure` no importa de otros slices; nadie importa de `handler`.
- La regla anterior no se sostiene con buena voluntad: se verifica con **import-linter**
  y con un **test de arquitectura ejecutado en CI** que falla el pipeline si hay imports
  cruzados entre slices.
- La documentación estructural (`../architecture/OVERVIEW.md`) refleja este mismo árbol.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| MVC / hexagonal clásico por capas (`controllers/`, `services/`, `models/`) | Esquema muy conocido; onboarding inmediato. | Agrupa por tipo: una feature queda dispersa en muchas carpetas; el cambio de una feature toca todas las capas a la vez. | Rompe el objetivo de poder entender y desplegar una feature de forma independiente. |
| Módulos por tipo `services/` (patrón del legacy) | Reutilización evidente entre handlers; código ya existente del que partir. | Acopla servicios no relacionados y recrea la dispersión que motivó el proyecto. | Reproduce la estructura que se está sustituyendo. |
| Monolito tipo el legacy (todo en un despliegue SAM con Lambda por endpoint) | Despliegue único, sin contratos entre piezas, cero fricción inicial. | Acoplamiento implícito, tests lentos y globales, escalado por bloque, imposible de migrar por partes. | El ADR 0006 exige reemplazo gradual slice a slice; un monolito no permite convivencia controlada. |

## Consecuencias

### Positivas

- Una feature se lee, se prueba y se despliega desde una sola carpeta.
- El `domain` es Python puro: tests rápidos, sin mocks de AWS.
- La frontera slice ↔ slice queda explícita y verificable en CI (ver ADR 0005).
- Sustituir el legacy avanza slice a slice sin tocar el resto (ver ADR 0006).

### Negativas / riesgos

- Más archivos y más carpetas por feature que en un módulo plano: el coste de navegación
  inicial sube y hay que explicarlo a quien llegue nuevo.
- Hay que mantener import-linter y el test de arquitectura en CI; si se relajan, la
  estructura se degrada en silencio.
- Riesgo de convertir `shared/` en un cajón de sastre; conviene revisarlo en cada PR.
- Existe la tentación de duplicar lógica entre slices en vez de extraerla a `shared/` o a
  un contract; requiere criterio en la revisión.

## Relacionados

- [0002. Reparto de datos: Aurora, DynamoDB y S3](0002-reparto-de-datos-aurora-dynamodb-s3.md)
- [0005. Comunicación entre slices vía contracts](0005-comunicacion-entre-slices-via-contracts.md)
- [0006. Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
- [Guía para agentes del repositorio](../../AGENTS.md)
