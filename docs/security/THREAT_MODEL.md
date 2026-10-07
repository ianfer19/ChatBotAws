# Modelo de amenazas

Documento de la Fase 1 (esqueleto). Qué defender, contra quién, con qué capas y cómo se
verifica. Es un documento vivo: cada slice nuevo o cada cambio de fase obliga a revisarlo.
Controles generales en [SECURITY.md](./SECURITY.md); aislamiento por tenant en
[../architecture/MULTI_TENANCY.md](../architecture/MULTI_TENANCY.md). Todo dato de AWS no
confirmado aparece como `TODO(verify)`.

Ver también: [../architecture/HEXAGONAL_AND_SLICING.md](../architecture/HEXAGONAL_AND_SLICING.md),
[../architecture/OVERVIEW.md](../architecture/OVERVIEW.md),
[../adr/README.md](../adr/README.md), [`../../AGENTS.md`](../../AGENTS.md).

## 1. Método

1. Se listan los **activos** (qué no puede perderse ni manipularse).
2. Se listan los **actores** (quién podría intentarlo y con qué capacidad).
3. Para cada amenaza se escriben al menos **dos mitigaciones en capas distintas**: si las
   dos viven en el mismo sitio, el fallo de esa capa elimina ambas.
4. Se indica **dónde se aplica** la mitigación (código, prompt, Guardrails, policy, datos,
   red, tests) y **cómo se verifica** (test o eval concreto).
5. Lo que un prompt no puede mitigar se declara fuera del prompt (sección 6).

## 2. Activos

| Activo | Dónde vive | Si lo pierdo o lo manipulan |
|---|---|---|
| Prompts por tenant | Bedrock Prompt Management + espejo en `prompts/` | Cambian personalidad, reglas y tono de un comercio; posible inyección de instrucciones persistentes |
| Datos de clientes (contexto, historial, preferencias) | DynamoDB (operacional), S3 (archivo), AgentCore Memory | Fuga de datos personales entre clientes o entre tenants |
| Conversaciones y media | DynamoDB con TTL → S3 (ver [DATA_RETENTION.md](./DATA_RETENTION.md)) | Lectura de transcripciones, imágenes y audios de clientes |
| Credenciales de canal Meta (app secret, tokens) | Secrets Manager (por tenant) | Suplantación del comercio, envío de mensajes en su nombre, lectura de webhooks |
| Catálogo, precios, stock, disponibilidad | Backend legacy (`sahagunonline/back`); copia de lectura en Aurora | Respuestas falsas al cliente y pérdida de confianza comercial |
| Pedidos y citas | Backend legacy, expuestos por tools vía AgentCore Gateway | Alteración de la operación real del comercio |
| Tokens de modelo y presupuesto de Bedrock | Cuentas AWS / roles de invocación | Denial of wallet: factura disparada sin valor entregado |
| Estado de la conversación en curso | DynamoDB (checkpointer de LangGraph) | Alteración del hilo para manipular el siguiente turno |
| Claves KMS y estado de Terraform (S3 + lock) | KMS, bucket de estado | Acceso a datos cifrados o despliegue manipulado |
| Logs y auditoría | CloudWatch (JSON con `tenant_id` y `correlation_id`) | Pérdida de trazabilidad e imposibilidad de investigar un incidente |

## 3. Actores

| Actor | Motivación | Capacidad esperada | Ejemplo |
|---|---|---|---|
| Cliente legítimo | Comprar, agendar, consultar | Acceso normal por WhatsApp/Instagram/Messenger | Pregunta precios o pide una cita |
| Cliente curioso | Probar límites, ver "hasta dónde llega el bot" | Acceso normal, sin intención maliciosa persistente | Pide que ignore sus instrucciones "de broma" |
| Competidor / curioso malicioso | Dañar la reputación o espiar información | Acceso como usuario, tiempo y paciencia | Intenta extraer el prompt o el stock de otro comercio |
| Bot externo (p. ej. Tigo u otros) | Tráfico automatizado no deseado en el canal | Envío automatizado de mensajes al número/respaldo del comercio | Ráfagas de mensajes o scripts que agotan límites |
| Insider (desarrollador u operador) | Acceso conveniente o malintencionado | Acceso a la cuenta AWS, a repos y a despliegues | Consulta datos de clientes fuera de su rol |
| Atacante de prompt | Manipular al modelo para robar o actuar | Solo el canal público; no tiene acceso al sistema | Injection, jailbreak o envenenamiento de contenido |

## 4. Tabla principal de amenazas

| Amenaza | Descripción | Mitigación | Capa donde se aplica |
|---|---|---|---|
| **Prompt injection directa** | El usuario escribe instrucciones que intentan sobreescribir el sistema: "ignora lo anterior", "responde solo con X", "olvida tus reglas". | 1. Jerarquía de instrucciones y *sandwich defense*: las reglas del sistema se repiten al inicio y al final del prompt, y el mensaje del usuario va en un bloque marcado como datos. 2. Filtros de prompt-attack de Bedrock Guardrails sobre la entrada. 3. Validación de la intención y de la salida en `domain/` y en `src/shared/contracts` (Pydantic): lo que no pasa el contrato no se ejecuta. 4. Rate limit por remitente y patrones de abuso en `abuse_protection`. | prompt · Guardrails · dominio/contratos · `abuse_protection` |
| **Prompt injection indirecta** (vía contenido que el RAG recoge) | El atacante coloca instrucciones en contenido que el sistema indexa o en el que el sistema apoya la respuesta; el modelo las sigue sin que el usuario las escriba. Ver diagrama en la sección 8. | 1. Separación datos/instrucciones: el contenido recuperado entra como `grounding_source` aislado del prompt de sistema, nunca como instrucción. 2. Contextual grounding con `ApplyGuardrail` (`grounding_source`, `query`, `guard_content`): la respuesta candidata se contrasta con la fuente y se rechaza si se desvía; umbrales 0–0.99 y `TODO(verify)` sobre el caso soportado de chat conversacional. 3. Ingesta controlada en `knowledge_rag`: solo fuentes del comercio, con `tenant_id` y provenance por chunk; nada de contenido de usuarios sin revisión. 4. Las acciones no las decide el texto recuperado: toda acción pasa por tools con AgentCore Policy en default-deny. | ingesta RAG · prompt/Guardrails · AgentCore Policy |
| **Prompt poisoning en RAG** | Alguien logra que un chunk envenenado ("cuando te pregunten X, responde Y / revela Z") quede en Aurora y sobreviva a muchas conversaciones. | 1. Control de escritura en el índice: solo la ingesta del comercio, publicada y versionada; sin escrituras desde el chat. 2. Separación de fuentes confiables (catálogo/políticas del comercio) y marcado de provenance por chunk, con auditoría de cada ingesta. 3. Dataset de regresión con chunks hostiles en `tests/agent_evals` que falla si el chunk gana sobre las reglas. | ingesta `knowledge_rag` · datos Aurora · evals |
| **Prompt leaking** | Extraer el prompt de sistema, reglas internas, prompts de otro tenant o datos ocultos mediante peticiones tipo "repite tus instrucciones" o "responde en JSON con tu configuración". | 1. Temas de revelación de instrucciones denegados en Guardrails, con respuesta de fallback y log con `correlation_id`. 2. El prompt de sistema no contiene secretos ni datos de otros tenants: instrucciones y datos van separados; los secretos viven en Secrets Manager. 3. Evals de fuga en `tests/agent_evals` (petición explícita de prompt → espera de bloqueo). 4. Logs de auditoría por intento para detectar reincidencia y bloquear con TTL. | Guardrails · prompt · evals/logging |
| **Jailbreaking** | Evadir las restricciones del sistema para obtener comportamiento no permitido (suplantar al comercio, obtener datos de otro tenant, ejecutar acciones prohibidas). | 1. Jerarquía de instrucciones en el prompt (sistema > herramientas > usuario) más *sandwich defense*. 2. Guardrails con temas denegados y filtros de ataque; bloqueo → fallback + log. 3. La autorización no depende del prompt: tools con autorización por tenant, AgentCore Policy default-deny y validación en `domain/` (ejemplo en la sección 5). 4. Reincidencia → rate limit y bloqueo temporal con TTL configurable, motivo en auditoría, desbloqueo manual. | prompt · Guardrails · AgentCore Policy/dominio · `abuse_protection` |
| **Denial of wallet** (agotamiento de tokens) | Sesiones largas, bucles de reintento o tráfico masivo que disparan la factura de Bedrock y de las tools sin entregar valor. | 1. Heurísticas baratas primero: rate limit por tenant y por remitente, límite de longitud de mensaje y de mensajes duplicados en el gateway. 2. Presupuesto por conversación en `supervisor`: ventana de historial controlada, resumen al superar el límite y tope de tokens/turnos por sesión. 3. Clasificador LLM solo si la heurística no basta (cuesta tokens, se usa en último lugar); bloqueo temporal con TTL y motivo en auditoría. 4. Métricas y alarmas de consumo por tenant en CloudWatch → `TODO(verify)` (métrica y umbral exactos). | gateway · `abuse_protection` · `supervisor` · observabilidad |
| **Bots externos (p. ej. Tigo u otros)** | Tráfico automatizado de terceros hacia el canal del comercio: ráfagas, plantillas repetidas, intentos de agotar límites o de secuestrar la conversación. | 1. Verificación de firma `X-Hub-Signature-256` + identidad de canal resuelta del mapeo oficial: solo los emisores mapeados llegan a procesar. 2. Heurísticas baratas: velocidad por remitente, longitud, duplicados y patrones conocidos → rate limit o bloqueo con TTL. 3. Clasificación solo si el heurístico duda; bloqueo con motivo en auditoría y desbloqueo manual (runbook `ABUSE_UNLOCK.md`, Fase 7, aún no creado). 4. Métricas por remitente/tenant y alarma de estallidos → revisión y calibración de umbrales. | gateway · `abuse_protection` · observabilidad · runbook |
| **Fuga entre tenants** | Un cliente o un error de código obtiene datos, prompts o respuestas de otro comercio; el peor caso es silencioso. | 1. `tenant_id` resuelto en el gateway y propagado en contexto; los schemas de tools no incluyen `tenant_id` y su valor en la salida del modelo se descarta. 2. Filtro por capa de datos: prefijo `ORG#{tenant_id}#` en DynamoDB, `WHERE tenant_id =` en Aurora, prefijo `/<tenant_id>/` en S3. 3. AgentCore Policy default-deny y forbid-wins por tenant sobre cada tool. 4. Tests de aislamiento A/B en `tests/integration` y `tests/contract`; cualquier respuesta con datos ajenos falla el build. | gateway/contexto · datos · AgentCore Policy · tests |

## 5. Ejemplo canónico de defensa en profundidad

El chatbot **no puede modificar la hora de un pedido**. La prohibición no vive en el prompt
sino en cinco capas independientes:

| Capa | Qué hace | Fase |
|---|---|---|
| 1. Tool inexistente | `orders` no expone ninguna tool de modificación de horario al LLM | 6 |
| 2. Dominio | `orders/domain` rechaza el cambio de `Order.scheduled_at` con un error tipado | 6 |
| 3. AgentCore Policy | La política del tenant deniega la acción (default-deny / forbid-wins) | 6/8 |
| 4. Guardrails | El tema queda denegado; bloqueo → fallback + log con `correlation_id` | 5 |
| 5. Regresión | Test en `tests/unit/` y eval en `tests/agent_evals/` que fallan si alguna capa se abre | 5/9 |

Detalle en [../architecture/HEXAGONAL_AND_SLICING.md](../architecture/HEXAGONAL_AND_SLICING.md).

## 6. Qué NO se puede mitigar con un prompt

| Lo que hay que proteger | Por qué el prompt no basta | Capa real |
|---|---|---|
| Reglas de negocio (no modificar horas, políticas de cancelación) | Un prompt se inyecta, se evade o el modelo alucina | `domain/` + tests de regresión |
| Autorización y aislamiento por tenant | El modelo no debe ni poder elegir sobre qué tenant opera | Contexto + validación de contratos + AgentCore Policy |
| Precios, stock, disponibilidad, estado de pedido, horas | El LLM no es fuente de verdad de nada de eso | Tools autorizadas y backend legacy |
| Presupuesto de coste y límites de tráfico | El modelo no negocia sus propios límites | Gateway, `abuse_protection`, alarmas |
| Borrado y retención de datos | Depende de almacenes y plazos, no del texto generado | DynamoDB TTL, lifecycle de S3, `retention_archiving` |
| Custodia de secretos | Un secreto en el prompt se filtra por la respuesta | Secrets Manager |

## 7. Denegación de servicio y abuso: umbrales y calibración

Heurísticas baratas primero; clasificador LLM solo si hace falta. Los valores de la tabla
son **propuestas iniciales de este repo, no límites de AWS**, y se calibran en la Fase 7 con
tráfico real (0 usuarios al inicio → se empieza en observación, no en bloqueo agresivo).

| Señal | Umbral inicial propuesto | Acción | Cómo calibrar (falsos positivos) |
|---|---|---|---|
| Mensajes por remitente | 10 / minuto | 429 y bloqueo temporal | Si clientes legítimos se bloquean, subir el umbral; registrar cada bloque con motivo |
| Mensajes por tenant | 120 / minuto | Encolado limitado con log `action=deny` | Observar estallidos normales (promoción, horario punta) en staging |
| Longitud del mensaje | 4096 caracteres | Descarte con `reason=too_long` | Revisar si algún canal legítimo envía audios transcritos largos |
| Firmas inválidas | 5 / minuto por origen | Rechazo sostenido + log de seguridad | Confirmar que no hay errores de configuración del app secret antes de bloquear |
| Tokens por conversación | Presupuesto por sesión configurable en `supervisor` | Corte con mensaje de fallback y log | Medir turnos reales por conversación antes de fijar el valor |
| Patrones de injection detectados | 3 / hora por remitente | Bloqueo temporal con TTL | Revisión manual de cada bloqueo; si hay falsos positivos, se relaja y se anota en el ADR de abuso |

Política de bloqueo: TTL configurable (empezar corto), **motivo siempre en auditoría** y
**desbloqueo manual** (runbook `ABUSE_UNLOCK.md`, Fase 7, aún no creado). Calibración: si
la proporción de bloqueos que terminan en revisión humana y se revierten es alta, se sube
el umbral; si hay reincidencia tras desbloquear, se baja. Los falsos positivos se llevan a
la revisión de la Fase 7 junto con [../adr/README.md](../adr/README.md).

## 8. Diagrama de ataque: inyección indirecta

```text
[Atacante] escribe instrucciones en un contenido que llegará al sistema
     |        (p. ej. texto en una fuente que el comercio publica o que se ingesta)
     v
[Ingesta knowledge_rag] ---- GATE A: solo fuentes del comercio, revisión y
     |                        provenance por chunk (+ tenant_id). Falla → no se indexa
     v
[Aurora + pgvector]  chunks con embeddings (conocimiento, SOLO conocimiento)
     |                        GATE B: dataset hostil en tests/agent_evals
     v
[Consulta RAG] recupera chunks ----> se inyectan como grounding_source,
     |                GATE C: separación datos/instrucciones en el prompt
     v
[Modelo (LLMPort)] genera respuesta candidata
     |                GATE D: ApplyGuardrail (grounding_source / query / guard_content),
     |                        umbrales 0-0.99; TODO(verify) caso conversacional
     |                        fallo → fallback + log con correlation_id
     v
[AgentCore Policy] revisa la acción que el modelo quiere ejecutar
     |                GATE E: default-deny por tenant; el texto recuperado no autoriza nada
     v
[Respuesta al cliente] o [acción vía tool autorizada]
     |                GATE F: dominio/contratos validan de nuevo (sección 5)
     v
[CloudWatch] log con correlation_id y tenant_id para investigar
```

Si algún gate se salta, lo que queda es texto sin autorización: la acción no ocurre porque
la autorización vive en las capas E y F, no en el contenido recuperado.

## 9. Verificación: amenaza → dónde se prueba

| Amenaza | Verificación | Fase |
|---|---|---|
| Inyección directa | Evals de ataque + tests de contrato de salida | 5/9 |
| Inyección indirecta | Evals con chunks hostiles + test de bloqueo de Guardrails | 5/9 |
| Poisoning en RAG | Test de ingesta (fuentes permitidas) + eval con dataset hostil | 5/9 |
| Prompt leaking | Eval de fuga de instrucciones → espera de bloqueo y log | 5/9 |
| Jailbreak | Evals de evasión + test de capa `domain/`/policy | 5/6/9 |
| Denial of wallet | Tests unitarios de límites y de presupuesto por sesión | 7/9 |
| Bots externos | Tests de rate limit y de firma inválida en `conversation_gateway` | 4/7 |
| Fuga entre tenants | Tests A/B de aislamiento en `tests/integration` y `tests/contract` | 4+ |

## 10. Referencias

- [SECURITY.md](./SECURITY.md) — principios, IAM, secrets y checklist de publicación.
- [DATA_RETENTION.md](./DATA_RETENTION.md) — retención y borrado de los datos afectados.
- [../architecture/MULTI_TENANCY.md](../architecture/MULTI_TENANCY.md) — mecanismos de aislamiento por capa.
- [../architecture/HEXAGONAL_AND_SLICING.md](../architecture/HEXAGONAL_AND_SLICING.md) — ejemplo canónico de defensa en profundidad.
- [`../../AGENTS.md`](../../AGENTS.md) — convenciones del repo.
