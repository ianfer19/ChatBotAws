# 0004. Orquestación: LangGraph, Bedrock y AgentCore modular

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El webhook Meta ya se encola y el orquestador tiene que decidir: recuperar contexto,
buscar en el conocimiento, llamar a una tool del legacy, generar respuesta, aplicar
guardrails, valorar sentimiento y, si toca, hacer handoff. Hoy ese flujo lo resuelve el
backend legacy: webhook Meta → SQS → orquestador LangGraph con **Step Functions**
(`ai_chat_service`).

Hay que elegir motor de orquestación y qué parte corre en Lambda gestionada y qué parte
se apoya en Bedrock AgentCore. Dos fuerzas empujan en direcciones distintas: el equipo
necesita poder probar y depurar el grafo desde el primer día, y producción pide las
piezas gestionadas de AWS (memoria, gateway de tools, identidad) sin reinventarlas.

## Decisión

Se decide una ruta **híbrida y gradual**:

- **Desarrollo:** grafo en **LangGraph** sobre **Amazon Bedrock** corriendo en **Lambda**.
  El grafo se versiona en el repositorio, se ejecuta igual en local y en dev, y se prueba
  con tests de nodo.
- **Producción:** despliegue **AgentCore modular**, incorporando los componentes en este
  orden: **Runtime → Memory → Gateway → Identity + Policy**. Cada paso es reversible y
  se activa cuando el componente anterior esté estable.
- Las tools de negocio se exponen al agente a través del **AgentCore Gateway** con su
  **Policy** asociada, llamando por HTTP a las APIs del backend legacy (ver ADR 0006).

Implica:

- El grafo LangGraph es la especificación ejecutable del flujo de conversación; no se
  duplica la lógica en otro motor.
- `src/adapters/agentcore/` y `src/adapters/bedrock/` contienen los adaptadores; el slice
  `supervisor/` depende de puertos, no del SDK concreto (ADR 0001).
- Dev y prod comparten la definición del grafo; cambia dónde se ejecuta, no qué hace.
- El orden de adopción de AgentCore queda fijado en este ADR: no se instala nada de
  Identity+Policy antes de que Memory y Gateway estén operativos.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Bedrock Agents gestionado desde el día 1 | Menos código propio; IAM y telemetría integrados. | Control limitado sobre el grafo y sobre el estado intermedio; migrar el flujo actual de LangGraph sería reescribirlo. | Se descarta porque el control del flujo es requisito explícito y LangGraph ya es la base del diseño. |
| Mantener Step Functions como hoy (`ai_chat_service`) | Infraestructura mental ya conocida del legacy; sin curva nueva. | El grafo queda definido en infraestructura y no en código de dominio; iterar un paso de conversación exige tocar recursos. | Se descarta por menor velocidad de iteración; se deja como referencia del legacy a sustituir. |
| AgentCore desde el día 1, incluida la parte de dev | Arquitectura final desde el principio; sin migración interna. | Bloquea el desarrollo ante la curva de una plataforma nueva; cualquier duda de la plataforma frena todo el proyecto. | Se descarta por riesgo en una fase con 3 comercios y 0 usuarios. |
| LangSmith gestionado como capa de orquestación/observabilidad | Traza y evaluación de LLM muy completas. | Añade un proveedor externo y otro punto de fallo; no resuelve la ejecución en producción. | Se descarta como dependencia; la observabilidad se cubre con la telemetría propia. |

## Consecuencias

### Positivas

- **Control total de la orquestación**: el grafo es código del repo, testeable nodo a
  nodo, con la lógica de negocio fuera del proveedor.
- **Adopción gradual**: cada componente de AgentCore se enciende por separado y se puede
  retroceder sin reescribir el grafo.
- Dev corre en Lambda y no consume plataforma gestionada, lo que mantiene barato el
  ciclo de desarrollo.
- El mismo flujo sirve para depurar con Bedrock y para servir en producción con
  AgentCore, sin bifurcaciones de comportamiento.

### Negativas / riesgos

- Dos entornos distintos (Lambda dev vs AgentCore prod) pueden divergir: requiere tests
  de contrato ejecutados en ambos.
- El coste de correr en Lambda frente al coste por sesión de AgentCore todavía no está
  contrastado: `TODO(verify pricing)`.
- LangGraph y el contrato de AgentCore son dependencias externas sujetas a cambio de
  versión: hay que fijar versiones y leer los release notes.
- La secuencia Runtime → Memory → Gateway → Identity+Policy retrasa el uso de features
  gestionadas hasta que cada paso se estabilice.

## Relacionados

- [0002. Reparto de datos: Aurora, DynamoDB y S3](0002-reparto-de-datos-aurora-dynamodb-s3.md)
- [0005. Comunicación entre slices vía contracts](0005-comunicacion-entre-slices-via-contracts.md)
- [0006. Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md)
- [0008. Contextual grounding en el chatbot](0008-contextual-grounding-en-chatbot.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
