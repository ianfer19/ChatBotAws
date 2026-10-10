# 0013. Checkpoint de conversación, ventana de historial y resumen

- **Estado:** Aceptado
- **Fecha:** 2026-10-10
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

El Paso 8 de la [ruta](../ROADMAP.md) exige que la conversación **sobreviva a
invocaciones distintas** (cada turno de WhatsApp es un proceso nuevo) y que **no haya
fuga de estado** entre conversaciones ni entre comercios, «con checkpointer de LangGraph
sobre un port y políticas de ventana + resumen». Fuerzas en conflicto:

1. El grafo del supervisor en `supervisor/application/graph.py` compila **sin**
   persistencia: `pending_outcome` (doble confirmación de ADR 0011), `summary` y
   `routed` se pierden entre turnos si nadie los guarda.
2. El ROADMAP dice «tras un port»: el almacenamiento no puede atarse a un SDK de
   LangGraph dentro del dominio ni de la aplicación.
3. Reenviar **todo** el historial en cada turno crece en tokens (costo) y en latencia
   con la ventana completa, y no transporta bien el state intermedio del grafo.
4. El `tenant_id` nunca sale del payload del LLM ni del usuario (regla D5 /
   [MULTI_TENANCY](../architecture/MULTI_TENANCY.md)): cualquier clave de partición
   derivada debe construirse solo con el contexto ya resuelto.

## Decisión

**Checkpointer custom sobre `MemoryStorePort` + ventana de historial con resumen
rodante, persistidos en una tabla DynamoDB dedicada.** Implica:

1. **`PortCheckpointSaver(BaseCheckpointSaver[str]`)** en `adapters/checkpointer/port.py`:
   traduce el protocolo de checkpoint de LangGraph (langgraph-checkpoint 4.2.0) a
   `put/get/delete` de `MemoryStorePort`. Cumple «tras port» y mantiene el dominio
   ajeno a AWS y a LangGraph (los tests usan `InMemoryMemoryStore`).
2. **Alcance: solo el grafo del supervisor** (compilación
   `graph.compile(checkpointer=…)` opcional). Los especialistas se invocan dentro del
   turno (ADR 0010) y no necesitan persistencia propia.
3. **`thread_id = <tenant_id>#<conversation_id>`** (`thread_id_de`, Fase 1): la
   partición por comercio viaja en la clave y se deriva siempre del contexto resuelto,
   nunca del payload del modelo.
4. **Solo el checkpoint más reciente**: el estado se guarda como envelope JSON v=1
   (incluye los writes pendientes del ciclo) en `MemoryStorePort.payload: str`;
   time-travel/ramas históricas de LangGraph → `TODO(verify)` (msgpack+base64 →
   `TODO(verify)` si el envelope JSON no basta).
5. **Ventana de historial + resumen** (nodo `window_history`): el clasificador ve
   `history_window_size` turnos por defecto (**N=10**, `CHATBOT_HISTORY_WINDOW_SIZE`);
   lo que desborda se condensa en un resumen rodante (un `llm.invoke` con
   `TAREA_RESUMEN`, `max_tokens=400` `TODO(verify)` de calibración con evals). Si la
   LLM falla, se conserva el resumen previo y se loguea `supervisor.summary_failed`
   (nunca se degrada el turno).
6. **Contrato de limpieza**: al iniciar un turno con checkpointer, `reply` y
   `route_error` (si estaban presentes) se vacían para no heredar respuestas de turnos
   previos; `pending_outcome` lo consume `resolve_pending` y `routed` lo consume el
   enrutador especialista (documentado en `supervisor/application/state.py`).
7. **Tabla dedicada `chatbot_checkpoints`** (Fase 4, decisión cerrada con el usuario):
   `PK=ORG#<tenant_id>`, `SK=CONV#<conversation_id>`, atributo `ttl` opcional; en los
   3 entornos, con IAM del supervisor limitado a `GetItem`/`PutItem`/`DeleteItem`
   (`TODO(verify)` de acciones mínimas) y env `CHATBOT_CHECKPOINTS_TABLE`.
   `DynamoDBMemoryStore` traduce `ClientError`/`BotoCoreError` a `ToolError` y los
   timeouts a `ToolTimeoutError`, con lectura fuerte y caducidad comprobada en lectura.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
|---|---|---|---|
| Paquete oficial de checkpoints DynamoDB de LangGraph | Mantenimiento upstream, sin código propio | No pasa por `MemoryStorePort` (el ROADMAP exige «tras port»); dependencia sin verificar y fuera de nuestro control de errores/timeouts | Se descarta; se revisará si el envelope propio se queda corto (`TODO(verify)`) |
| Memory de AgentCore como estado de corto plazo | Memoria gestionada y con retentiones | Acoplaría el Paso 8 al Paso 10; el ROADMAP separa ambos y ADR 0004 exige adopción modular | Se descarta: después se podrá migrar el mismo port a AgentCore Memory |
| Sin checkpoint: reenviar todo el historial cada turno | Cero estado que persistir | Costo/latencia crecen con el historial; `pending_outcome`/`summary` no viajan bien en el payload | Se descarta: no cumple el criterio de sobrevivir invocaciones con estado intermedio |
| Reusar `chatbot_conversations` como checkpoint | Una tabla menos | Mezcla mensajes (retención de ADR 0007) con estado vivo de grafo (retención y TTL distintos) | Se descarta: tabla dedicada, decisión ya tomada con el usuario |
| Ventana sin resumen (solo los últimos N turnos) | Un nodo menos, sin llamada LLM | Al desbordar se pierde el contexto de turnos lejanos (ventas/citas largas) | Se descarta: el resumen rodante lo conserva con un costo acotado (evals lo verifican) |

## Consecuencias

### Positivas

- La conversación sobrevive a procesos distintos y **no hay fuga de estado**: claves
  `ORG#…/CONV#…` + `thread_id` con tenant (tests de Fase 3).
- El dominio y la aplicación siguen sin saber de DynamoDB: todo pasa por
  `MemoryStorePort`, con doble en memoria para tests y evals.
- El clasificador ve siempre una ventana acotada (costo estable) y conserva el
  contexto lejano vía resumen.
- Tabla, IAM y env por entorno ya desplegables con `terraform validate` sin
  credenciales (ADR 0012).

### Negativas / riesgos

- **Solo el checkpoint más reciente**: no hay depuración temporal del state de grafo
  (time-travel `TODO(verify)`); un envelope corrupto se descarta en lectura.
- Cada ventana desbordada cuesta una llamada a la LLM de resumen (costo → Paso 14);
  `max_tokens=400` está sin calibrar (`TODO(verify)`).
- El TTL de `chatbot_checkpoints` depende de la política de retención final, que sigue
  **pendiente** en [ADR 0007](0007-retencion-de-conversaciones-y-media.md).
- El adapter DynamoDB solo está probado con dobles; la verificación contra AWS real
  queda para un test `integration` con credenciales de dev.

## Relacionados

- [ROADMAP §1 fila 8](../ROADMAP.md) · [MEMORY_AND_CONTEXT](../ai/MEMORY_AND_CONTEXT.md)
- [ADR 0004](0004-orquestacion-langgraph-agentcore-modular.md) (AgentCore modular) ·
  [ADR 0007](0007-retencion-de-conversaciones-y-media.md) (retención) ·
  [ADR 0010](0010-composicion-de-grafos-por-invocacion.md) (alcance: solo supervisor) ·
  [ADR 0011](0011-confirmacion-por-politica-con-drafts.md) (`pending_outcome`) ·
  [ADR 0003](0003-multi-tenancy-tenant-en-gateway.md) (tenant en la clave)
- [DATA_MODEL §DynamoDB](../architecture/DATA_MODEL.md) ·
  [MULTI_TENANCY](../architecture/MULTI_TENANCY.md) ·
  [EVALUATION](../ai/EVALUATION.md) (calibración de la ventana y del resumen)
