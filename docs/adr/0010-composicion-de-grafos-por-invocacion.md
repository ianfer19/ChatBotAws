# 0010. Composición de grafos por invocación

- **Estado:** Aceptado
- **Fecha:** 2026-10-08
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El supervisor del Paso 4 decide la intención del turno (`greeting`, `sales`,
`appointments`, `orders`, `faq`) y debe entregarlo al agente especialista adecuado.
Cada especialista es un slice con su propio grafo de LangGraph, su propio schema de
estado, sus propios nodos y sus propias tools: el primero, `appointments` (Paso 3), ya
existe y funciona en su REPL y su smoke.

Surge entonces la pregunta estructural de cómo se relacionan el orquestador y los
especialistas sin romper la regla de dependencia del repositorio: los slices **nunca se
importan entre sí** y se comunican solo vía `shared/contracts` (verificado en CI con
import-linter y el test AST). Además, el supervisor debe poder enrutar a futuros
especialistas (`sales`, `orders`, `faq`) sin conocer sus estados internos, y los
especialistas deben poder probarse e invocarse de forma aislada (así ya lo hacen su
REPL y su smoke).

## Decisión

El supervisor **compone a los especialistas por invocación**: el nodo de enrutado
(`route_appointments`, y en el futuro `route_orders`, `route_faq`, ...) llama al grafo
especialista ya compilado como si fuera una función, a través del puerto de dominio
`SpecialistGraphPort`, sin importar nunca el slice que lo implementa.

Implica:

- `SpecialistGraphPort` (`supervisor/domain/ports.py`) declara `invoke(input) -> Any`;
  el grafo de citas y los futuros lo cumplen sin depender del supervisor.
- El payload de entrada es el contrato mínimo y estable: `tenant_id`,
  `correlation_id`, `user_message` e `history` (mismo contrato que el state del
  especialista; no se filtran estados internos ni tools).
- El nodo de enrutado devuelve al supervisor solo un subconjunto del resultado
  (`reply` y el contrato `RoutedTurn` con `target`); el estado rico del especialista
  (citas creadas, `missing_fields`...) se lee desde su propio repo o estado, no se
  vuelca en el state del supervisor.
- La composición ocurre **fuera** del slice: el handler futuro, el REPL
  (`scripts/chat_citas.py`) y los tests construyen ambos grafos y los ensamblan con
  `build_supervisor_graph(..., appointments_graph=...)`; el supervisor recibe el
  especialista ya construido.
- `tenant_id` y `correlation_id` se reenvían intactos de `InboundMessage` al
  especialista: la identidad del turno no se regenera nunca (requisito 7.1).
- La misma fórmula se usará para `sales`, `orders` y `faq` cuando sus grafos existan
  (Paso 5 y Paso 7): un nodo de enrutado por especialista y su puerto correspondiente.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Subgrafo embebido (`add_node("appointments", subgraph)` de LangGraph) | Integración "de fábrica" con el estado de LangGraph; mensajes fluirían por el mismo checkpointer. | Exige que el supervisor importe el slice de citas y conozca su schema de estado (rompe el aislamiento verificado en CI); el estado del supervisor pasaría a ser la unión de todos los especialistas; no sirve para especialistas aún no escritos. | Se descarta por acoplamiento: el orquestador no debe saber cómo se modela cada agente. |
| Un único grafo gigante con estado compartido (`AgentState` común a todos los agentes) | Un solo `invoke` y un solo checkpointer; navegación centralizada. | Estado único con campos de todos los dominios (citas + pedidos + faq); cualquier especialista puede escribir campos ajenos; cambios en un agente recalientan a todos; contradice el slicing vertical. | Se descarta por la misma razón: el estado deja de ser propiedad de cada dominio. |
| Mensajería asíncrona entre slices (SQS/event bus por turno) | Desacople total y escalado independiente por agente. | Añade latencia y pérdida de localidad de turno (la respuesta debe salir en el mismo webhook); operación y coste de colas antes del Paso 6; difícil de probar en un REPL. | Se descarta como mecanismo de composición in-process: las colas sirven para desacoplar servicios (ADR 0006), no para llamar a un grafo en memoria. |

## Consecuencias

### Positivas

- El aislamiento de slices se mantiene intacto: el supervisor no importa a
  `appointments` ni a ningún futuro especialista (import-linter y test AST siguen en verde).
- Cada especialista se prueba, versiona y despliega por su lado; su REPL y su smoke
  siguen funcionando sin el supervisor.
- Añadir un especialista = nuevo puerto de dominio + nodo de enrutado + ensamblaje en
  la composición; el núcleo del supervisor (clasificar/decidir) no cambia.
- El payload de entrada al especialista es un contrato pequeño y estable
  (`tenant_id`, `correlation_id`, `user_message`, `history`).

### Negativas / riesgos

- Cada invocación es una copia de estado aparte: hoy no hay un checkpointer único que
  cubra supervisor y especialista en el mismo turno; la persistencia entre turnos se
  resuelve en el Paso 8 (`TODO(decision)`: checkpointer único vs. uno por grafo).
- Solo se propaga `reply` (y `RoutedTurn`): los estados internos del especialista no
  son visibles en el supervisor, que debe leerlos por su propio lado si algún día los
  necesita (métricas, confirmaciones).
- Un nodo de enrutado por especialista añade ramas condicionales al supervisor; hay
  que mantener la allowlist de tools mínima de cada agente (principio de mínimo
  privilegio).
- Si dos grafos comparten un LLM, el coste por turno se multiplica según las llamadas
  de cada grafo (`TODO(verify pricing)` en el Paso 14).

## Relacionados

- [0001. Arquitectura hexagonal y vertical slicing](0001-arquitectura-hexagonal-y-vertical-slicing.md)
- [0004. Orquestación: LangGraph, Bedrock y AgentCore modular](0004-orquestacion-langgraph-agentcore-modular.md)
- [0005. Comunicación entre slices vía contracts](0005-comunicacion-entre-slices-via-contracts.md)
- [Slice supervisor](../../src/slices/supervisor/AGENTS.md)
- [Guía hexagonal y de slicing](../architecture/HEXAGONAL_AND_SLICING.md)
