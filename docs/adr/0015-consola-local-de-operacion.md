# 0015. Consola local de operación (Fase A)

- **Estado:** Aceptado
- **Fecha:** 2026-11-07
- **Decisores:** Plataforma ChatBotAws

## Contexto

Hoy la única forma de conversar con el agente es el REPL `scripts/chat_citas.py` o el
webhook real de Meta. Ninguna de las dos sirve para que una persona de soporte pruebe
prompts, cambie el nombre de un comercio o revise la traza de un turno sin tocar código.
Además, el prompt se carga de `prompts/base/*.md` al compilar el grafo y el saludo usa
el `tenant_id` como nombre comercial.

La consola debe funcionar **sin AWS** para el desarrollo diario y reutilizar el grafo
real, no una maqueta. La interfaz elegida es Astro (que usa Vite por dentro) con islas de
React; la API es FastAPI.

## Decisión

Añadir una **consola local** en `web/` + `src/handlers/console_api.py` con estas reglas:

1. **Simulador, no canal:** construye un `InboundMessage` con `channel="whatsapp"` y
   `emitter_id="console"` y llama al grafo; no envía nada a Meta.
2. **Un runtime por comercio:** stores en memoria aislados y un grafo recompilado cuando
   cambia el perfil. El checkpointer usa `thread_id = tenant#console:<sesión>`.
3. **Perfil y prompts en JSON local** (`console-data/tenants.json`, ignorado por git)
   mediante el slice `tenant_prompts`. La Fase B cambiará el repositorio por Bedrock
   Prompt Management + DynamoDB sin tocar la API.
4. **Override de prompt inyectado:** `build_supervisor_graph`, `build_appointment_graph`,
   `build_order_graph` y `build_faq_graph` aceptan `system_prompt` opcional; si falta,
   se conserva `prompts/base/*.md`. `build_supervisor_graph` acepta `tenant_name` para el
   saludo.
5. **LLM con modo `auto`:** Bedrock si hay modelo y credenciales; simulador determinista
   en caso contrario, con aviso visible en la interfaz.
6. **Sin autenticación y solo `127.0.0.1`:** es una herramienta local; no se despliega en
   la Fase A.
7. **Frontend Astro + React:** Astro aporta el shell y el build estático; React se usa
   solo en las islas interactivas (`client:only="react"`).

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
|---|---|---|---|
| Extender el REPL con una TUI | Cero dependencias nuevas | No es visual ni editable; difícil de compartir con soporte | No cumple el objetivo |
| React + Vite puro | Ecosistema conocido | Se pierde el shell/routing de Astro que el usuario prefiere | El usuario pidió Astro |
| Astro + Vanilla TS | Menos dependencias | Mucho código manual para chat, formularios y estado | React acelera la Fase A |
| Servir la UI desde FastAPI | Un solo proceso | Mezcla framework web con la composición y complica el build | Astro/Vite ya resuelve el frontend |
| Guardar prompts en Bedrock ya en la Fase A | Una sola fuente de verdad | Exige credenciales, cuotas y verificación de API antes de tener UI | Se pospone a la Fase B |

## Consecuencias

### Positivas

- Se puede probar el flujo completo sin AWS y sin tocar Meta.
- El prompt editable llega al mismo nodo que en producción: lo que se prueba es el grafo
  real, no una simulación de la conversación.
- La Fase B solo sustituye el repositorio de `tenant_prompts` y añade versionado.
- La UI queda separada del backend y puede desplegarse como estático en S3+CloudFront.

### Negativas / riesgos

- El JSON local no es multi-usuario ni concurrente entre máquinas; es una herramienta de
  desarrollo.
- El simulador no refleja el prompt; la UI lo advierte y el modo `auto` intenta Bedrock.
- El catálogo, horarios y conocimiento son sintéticos; el POS real llega en la Fase C.
- El historial de chat no sobrevive a un reinicio del proceso.
- FastAPI y Astro añaden dependencias de desarrollo que no entran en el zip de Lambda.

## Relacionados

- [ADR 0014](0014-composition-root-en-handlers.md) — composition root en `src/handlers/`.
- [ADR 0011](0011-confirmacion-por-politica-con-drafts.md) — drafts y confirmación.
- [ADR 0013](0013-checkpoint-de-conversacion-y-ventana-de-historial.md) — checkpointer.
- [Consola local](../architecture/CONSOLE.md) — guía operativa.
