# 0003. Multi-tenancy: tenant resuelto en el gateway

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

ChatBotAws es multi-comercio (multi-tenant): arranca con 3 comercios y crecerá desde ahí.
Cada comercio tiene su propio catálogo, sus prompts, sus reglas de handoff y sus datos de
conversación. Cualquier fuga de datos entre comercios es un incidente grave, no un bug
menor.

La identidad de tenant ya existe en el backend legado: es el `store_id`, un string con
forma de `"Sede_Elite_01"`. Los webhooks de Meta llegan identificados por número de
teléfono/usuario, no por comercio, así que en algún punto hay que mapear "quién escribe"
→ "de qué comercio es". Además, el LLM es una pieza que intenta rellenar huecos por su
cuenta: si el tenant se le infiere o se le pide al modelo, puede inventarlo.

Hay que decidir **una sola vez dónde se resuelve el tenant y cómo viaja después**, para
que 13 slices no lo resuelvan cada uno a su manera.

## Decisión

El tenant se resuelve **una única vez en `conversation_gateway`**, al entrar el webhook, y
después **se propaga explícitamente en el contexto de la petición** a todos los slices y
tools.

Implica:

- `tenant_id` **es** el `store_id` legado, conservando el valor string original
  (p. ej. `"Sede_Elite_01"`) para poder enlazar con los datos del legacy sin traducción.
- La resolución ocurre en el gateway (capa `infrastructure/` del slice
  `conversation_gateway`), a partir de la identidad del canal, antes de encolar a SQS.
- El valor se guarda en un objeto de contexto (`src/shared/context/`) que acompaña el
  mensaje desde el handler hasta la tool correspondiente.
- **Toda query y toda tool filtra por `tenant_id`**: consultas a Aurora, a DynamoDB, a S3
  y llamadas a APIs del legacy llevan el tenant como parámetro obligatorio del contract.
- El tenant **nunca** se infiere del LLM ni se lee de la respuesta del modelo: si el
  contexto no trae `tenant_id`, se rechaza la petición.
- El modelo recibe solo el hecho de "para qué comercio responde", no la responsabilidad
  de determinarlo.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Resolver el tenant por request en cada capa/slice | Cada slice es autosuficiente; no depende de un contexto compartido. | 13 puntos de resolución que pueden divergir; coste de lookup repetido; un slice olvidado es una fuga de datos. | Se descarta por duplicación y por el riesgo de olvidos difíciles de detectar. |
| JWT con el tenant como claim, validado en cada invocación | Estándar, estadoless, verificación criptográfica. | Los mensajes llegan de Meta, no de un cliente con JWT: habría que emitir y rotar tokens propios; añade una superficie de identidad nueva sin resolver nada que el gateway no resuelva ya. | Se descarta por complejidad añadida sin un requisito de autorización por cliente. |
| Subdominio o número de teléfono como identidad de tenant | Aparentemente "gratis", usable como clave en URL. | Un número puede escribir a varios comercios y un comercio tiene varios números; el mapeo sigue existiendo y se esconde en la capa de red. | Se descarta porque traslada el problema en vez de resolverlo. |

## Consecuencias

### Positivas

- Un único punto de control para el aislamiento: se audita y se prueba en un solo lugar.
- El filtrado por `tenant_id` es mecánico: se comprueba en los tests de cada slice.
- Al coincidir con el `store_id` legado, las tools HTTP al backend no necesitan tabla de
  traducción de identidades.
- Cambiar el mecanismo de resolución (número → comercio) no afecta a ningún slice: solo
  al gateway.

### Negativas / riesgos

- El contexto compartido es un contrato interno: si un slice no lo recibe o lo ignora,
  filtra por defecto. Mitigado con firmas tipadas (Pydantic, ver ADR 0005) y tests.
- Una sola resolución implica un coste de lookup por mensaje. Con 3 comercios es
  despreciable, pero hay que cachear el mapeo y medirlo cuando entre el cuarto comercio
  `TODO(verify)`.
- Si en el futuro llega un canal que identifique al comercio de otra forma (web, QR en
  tienda), habrá que extender la resolución del gateway sin romper el contrato.
- El filtrado depende de disciplina: una query sin `tenant_id` es un bug de seguridad.
  Debe cubrirlo un test de regresión por slice.

## Relacionados

- [0005. Comunicación entre slices vía contracts](0005-comunicacion-entre-slices-via-contracts.md)
- [0006. Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md)
- [0008. Contextual grounding en el chatbot](0008-contextual-grounding-en-chatbot.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
- [Guía para agentes del repositorio](../../AGENTS.md)
