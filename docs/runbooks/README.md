# Runbooks

Índice de runbooks de ChatBotAws: procedimientos operativos escritos, revisados y
probados para situaciones que no se resuelven "mirando el código". Un runbook se ejecuta en
medio de un incidente: por eso la convención de la sección 3 es estricta.

Ver también: [../security/THREAT_MODEL.md](../security/THREAT_MODEL.md),
[../security/SECURITY.md](../security/SECURITY.md),
[../architecture/OVERVIEW.md](../architecture/OVERVIEW.md),
[`../../AGENTS.md`](../../AGENTS.md).

## 1. Índice

| Runbook | Descripción | Paso | Estado |
|---|---|---|---|
| `ROLLBACK_PROMPT.md` | Revertir la versión de prompt de un tenant a la anterior en Bedrock Prompt Management cuando una versión nueva degrada las respuestas | fuera de ruta | Pendiente (aún no creado) |
| `HANDOFF_HUMAN.md` | Ejecutar y dar soporte al traspaso de una conversación a un agente humano (sentimiento negativo o petición explícita) sin perder contexto | fuera de ruta | Pendiente (aún no creado) |
| `ABUSE_UNLOCK.md` | Revisar y desbloquear un remitente o tenant bloqueado por `abuse_protection`, con motivo en auditoría y registro de la decisión | fuera de ruta | Pendiente (aún no creado) |

Los tres archivos **aún no existen**: este índice es su plan. Se crean en el paso indicado
y, mientras tanto, no se ejecuta ningún procedimiento informal en su lugar.

Runbooks futuros (propuestos, sin fecha): respuesta a incidente de seguridad, degradación
de Bedrock/modelo, y recuperación de un despliegue de Terraform → `TODO(decision)` (si
alguno de ellos se decide, se añade a esta tabla con su paso).

## 2. Cuándo se crea un runbook

- Cuando una operación tiene pasos que alguien puede olvidar bajo presión (cambios de
  prompt, desbloqueos, handoffs, rotaciones de secreto).
- Cuando un incidente se resuelve más de una vez con los mismos pasos.
- Cuando una amenaza de [../security/THREAT_MODEL.md](../security/THREAT_MODEL.md) define
  una acción reactiva (p. ej. bloqueo → desbloqueo con revisión).
- No se crea runbook para tareas de desarrollo habitual: eso es el README del slice.

## 3. Convención: qué debe tener todo runbook

Todo archivo `docs/runbooks/*.md` tiene, en este orden:

| Sección | Qué debe contener | Regla |
|---|---|---|
| Título y estado | Nombre en mayúsculas, paso, estado (`Pendiente` / `Aprobado` / `Obsoleto`) | El estado se actualiza en el mismo PR que lo aprueba |
| Prerequisitos | Accesos necesarios (entorno, rol), herramientas, qué hay que saber antes de tocar nada | Sin accesos claros, el runbook no empieza |
| Señales / disparador | Qué síntoma o alerta indica que hay que usar este runbook | Enlazar a la métrica o al log, no a "cuando el cliente se queja" |
| Pasos verificables | Pasos numerados, cada uno con el comando o la ruta exacta y **cómo comprobar que salió bien** | Cada paso deja una comprobación; si no se puede comprobar, no es un paso |
| Rollback | Cómo deshacer lo hecho, con los mismos criterios de verificación | Obligatorio aunque el cambio parezca trivial |
| Contacto y escalado | Quién aprueba, quién ejecuta y a quién se escala (rol, no persona) | Sin contacto no hay runbook |
| Registro | Qué se deja escrito después de ejecutarlo (incidente, `correlation_id`, decisión) | El registro es parte del procedimiento, no opcional |

Reglas complementarias: documentación en español (identificadores y rutas en inglés), sin
secretos en los ejemplos (usar `<APP_SECRET>`, `<TENANT_ID>`), sin emojis, comandos
copiables y sin pasos "y entonces arreglarlo".

### Plantilla mínima

````markdown
# <NOMBRE_DEL_RUNBOOK>

- **Paso:** <n> · **Estado:** Pendiente | Aprobado | Obsoleto
- **Última prueba:** YYYY-MM-DD (<entorno>)

## Señales / disparador
<qué alerta o síntoma indica que hay que usar este runbook>

## Prerequisitos
- Rol/entorno necesarios, herramientas, qué hay que saber antes de empezar.

## Pasos
1. <acción exacta, comando o ruta>
   - Verificación: <cómo confirmo que este paso salió bien>
2. <siguiente acción>
   - Verificación: <comprobación>

## Rollback
1. <cómo deshago el paso 1> · Verificación: <comprobación>

## Contacto y escalado
- Ejecuta: <rol> · Aprueba: <rol> · Escala a: <rol>

## Registro
<qué se deja escrito tras ejecutarlo: incidente, correlation_id, decisión>
````

## 4. Estados y ciclo de vida

| Estado | Significado |
|---|---|
| `Pendiente` | El índice lo referencia pero el archivo no existe o no está probado |
| `Aprobado` | Escrito, revisado y probado al menos una vez en un entorno no productivo |
| `Obsoleto` | La operación ya no existe (p. ej. se retiró un componente); se conserva con la razón y el sustituto |

Un runbook que cambia de `Pendiente` a `Aprobado` lo hace en el mismo PR que lo prueba; el
revisor verifica los pasos contra el sistema real, no solo la redacción.

## 5. Cómo reportar un incidente

1. **No rompas la evidencia**: si el sistema sigue corriendo, no borres logs ni tablas.
2. **Reúne los tres identificadores** que todo log de este sistema lleva:
   - `correlation_id` — traza de la conversación o del lote afectado;
   - `tenant_id` — comercio afectado;
   - marca temporal (UTC) y entorno (`dev` / `staging` / `prod`).
3. **Búsqueda en CloudWatch**: los logs son JSON por línea con `tenant_id` y
   `correlation_id` obligatorios; filtrar por `correlation_id` reconstruye el hilo completo
   (webhook → SQS → supervisor → tools → respuesta). Un log sin `tenant_id` se considera bug
   del logger y también se reporta.
4. **Clasifica la severidad**:

   | Severidad | Ejemplo | Respuesta |
   |---|---|---|
   | Alta | Fuga entre tenants, secreto expuesto, facturación anómala (denial of wallet) | Aviso inmediato + [../security/THREAT_MODEL.md](../security/THREAT_MODEL.md) y, si aplica, [../security/SECURITY.md](../security/SECURITY.md) sección 7.1 |
   | Media | Respuestas degradadas, handoff caído, bloqueos masivos de clientes legítimos | Runbook correspondiente + registro del incidente |
   | Baja | Unidad aislada, sin cliente afectado | Registro y revisión en la siguiente iteración |

5. **Ejecuta el runbook** si existe en la sección 1; si no existe, documenta los pasos que
   seguiste: eso es el borrador del próximo runbook.
6. **Deja registro**: incidente, `correlation_id`, qué se hizo, resultado y rollback si lo
   hubo. El registro alimenta la revisión de los Pasos 13–14 (observabilidad y evals).

## 6. Checklist antes de ejecutar un runbook

- [ ] Confirmé entorno (`dev` / `staging` / `prod`) y `tenant_id` afectado.
- [ ] Tengo los accesos listados en prerequisitos (rol, no credenciales compartidas).
- [ ] Entiendo el rollback antes de empezar.
- [ ] Hay una persona/rol avisada si el paso sale mal.
- [ ] Voy a anotar `correlation_id` y hora de cada paso verificable.

## 7. Referencias

- [../security/THREAT_MODEL.md](../security/THREAT_MODEL.md) — amenazas y acciones reactivas.
- [../security/SECURITY.md](../security/SECURITY.md) — principios, IAM y checklist de publicación.
- [../security/DATA_RETENTION.md](../security/DATA_RETENTION.md) — borrado de datos (derecho de supresión).
- [../adr/README.md](../adr/README.md) — decisiones registradas y su estado.
- [`../../AGENTS.md`](../../AGENTS.md) — convenciones del repo.
