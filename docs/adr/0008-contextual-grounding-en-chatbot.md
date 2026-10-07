# 0008. Contextual grounding en el chatbot

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El chatbot responde con RAG: `knowledge_rag` recupera chunks del catálogo en Aurora
(pgvector) y el orquestador los entrega al modelo (ADR 0002, ADR 0004). Dos problemas
aparecen enseguida: la respuesta puede apoyarse en lo que el modelo "sabe" de su
entrenamiento en vez de en los chunks, y puede revelar o inventar cosas que el comercio
no quiere que se digan.

AWS ofrece Bedrock Guardrails con una operación `ApplyGuardrail` que admite
`grounding_source` (el material que debe sustentar la respuesta), `query` (lo que pidió
el usuario) y `guard_content` (el contenido a evaluar), con umbrales entre 0 y 0.99.
Pero la documentación de AWS **no lista explícitamente el caso "chatbot / QA
conversacional"** entre los casos soportados del contextual grounding check, aunque
sí lo son la detección de datos personales, los filtros de contenido y las
instrucciones de sistema.

Hay que decidir cómo se aplica la verificación de fundamentación sin afirmar una
capacidad que la documentación no garantiza.

## Decisión

Se aplica **`ApplyGuardrail` sobre la respuesta RAG generada**, con
`grounding_source` = los chunks recuperados, `query` = la pregunta del usuario y
`guard_content` = la respuesta del modelo, usando **umbrales en el rango 0–0.99**.

Implica:

- El guardrail se ejecuta **después** de generar la respuesta y **antes** de devolverla
  al canal; el modelo no ve el resultado de la evaluación.
- El uso del contextual grounding para QA conversacional queda marcado como
  **`TODO(verify)`**: hay que confirmarlo con la documentación vigente y con una prueba
  antes de depender de él.
- Mientras tanto, los guardrails de contenido, datos personales e instrucciones de
  sistema sí se aplican sin reserva, y el prompt de sistema restringe responder fuera
  del material entregado (defensa redundante).
- **Comportamiento en bloqueo**: no se responde con lo que se censuró. Se envía un
  fallback neutro del tenant, se registra el evento con `correlation_id` y el turno
  queda trazado para revisión; no se reintenta con otro modelo ni se degrada el umbral
  en caliente.
- El ADR 0003 prohíbe que el tenant salga del contexto: el guardrail se evalúa siempre
  con el `tenant_id` resuelto, nunca con uno inferido.

### Ejemplo canónico de defensa en profundidad

**El chatbot no puede modificar la hora de un pedido**, y esa restricción se sostiene en
cinco capas, ninguna de las cuales basta por sí sola:

1. **Tool inexistente**: no hay operación de escritura de agenda de pedidos en el catálogo
   de tools que ve el agente.
2. **Regla en `orders/domain`**: la función de dominio rechaza cambios de horario, con
   test unitario propio.
3. **AgentCore Policy (deny)**: el Gateway deniega la operación aunque se invocara.
4. **Guardrails**: el tema se detecta y bloquea en la respuesta.
5. **Test de regresión**: un caso de prueba cubre el intento completo y falla el
   pipeline si cualquiera de las capas anteriores se afloja.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Confiar solo en el prompt ("responde solo con el contexto") | Cero coste y cero latencia añadida. | No es verificable; el modelo se salta la instrucción de forma no determinista. | Se descarta por no ser una garantía: es una petición, no un control. |
| Validar la respuesta con un segundo modelo ("LLM como juez") | Flexible y comprensible. | Otro coste y otra latencia por turno; introduce un fallo nuevo; también puede fallar. | Se descarta como control principal; se reserva como posible herramienta de evaluación offline. |
| Aplicar el contextual grounding como lo describe AWS y darlo por cubierto | Aprovecha el servicio gestionado completo. | La documentación no lista el QA conversacional como caso soportado: afirmarlo sería incorrecto y podría dejar de funcionar sin aviso. | Se descarta como certeza; se adopta como implementación con `TODO(verify)` y defensa redundante. |

## Consecuencias

### Positivas

- La respuesta se contrasta contra el material recuperado antes de salir, con medida
  numérica (umbrales 0–0.99) en lugar de con una instrucción al modelo.
- El bloqueo queda auditado con `correlation_id`, lo que permite medir la tasa de
  intervención por comercio.
- La defensa en profundidad del ejemplo canónico sigue funcionando aunque una capa
  falle o desactive.
- Se documenta honestamente el límite de soporte en vez de ocultarlo.

### Negativas / riesgos

- `ApplyGuardrail` añade una llamada por turno: latencia y coste adicionales
  (`TODO(verify pricing)`).
- El contextual grounding aplicado a un caso no listado puede comportarse de forma
  distinta a la esperada: `TODO(verify)`.
- Umbrales mal calibrados generan falsos positivos (respuestas legítimas bloqueadas) o
  falsos negativos; hay que ajustarlos con tráfico real.
- El fallback neutro puede frustrar al usuario si se dispara con frecuencia: requiere
  revisión periódica de los registros.

## Relacionados

- [0003. Multi-tenancy: tenant resuelto en el gateway](0003-multi-tenancy-tenant-en-gateway.md)
- [0004. Orquestación: LangGraph, Bedrock y AgentCore modular](0004-orquestacion-langgraph-agentcore-modular.md)
- [0006. Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md)
- [0007. Retención de conversaciones y media](0007-retencion-de-conversaciones-y-media.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
- [Notas de seguridad](../security/THREAT_MODEL.md)
