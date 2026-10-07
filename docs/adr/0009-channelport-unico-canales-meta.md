# 0009. ChannelPort único para los canales Meta

- **Estado:** Aceptado
- **Fecha:** 2026-10-07
- **Decisores:** Arquitecto de la plataforma ChatBotAws

## Contexto

La plataforma debe atender los tres canales Meta que Sahagún Online usa hoy:
**WhatsApp**, **Instagram** y **Messenger**. Los tres llegan por el mismo mecanismo de
webhook, comparten verificación (`hub.challenge`), firma (`X-Hub-Signature-256`) y encola
a SQS (ADR 0006), pero difieren en el formato del payload, en los tipos de mensaje
soportados (texto, imagen, audio, ubicación, plantillas) y en cómo se contesta.

Desde dentro del grafo de orquestación, el canal no debería importar: el nodo de
respuesta necesita "enviar esto a este usuario en este comercio", sin saber si es un
WhatsApp o un DM de Instagram. Con 3 comercios ya conviviendo y la posibilidad de añadir
más canales después, hay que fijar una única frontera entre el dominio de conversación y
la transportística de cada canal.

## Decisión

Se define **un único puerto, `ChannelPort`**, en `src/shared/ports/`, con adaptadores
(concretos) por canal bajo
`src/slices/conversation_gateway/infrastructure/channels/`.

Implica:

- `ChannelPort` declara las operaciones mínimas del dominio: normalizar entrante,
  clasificar tipo de mensaje, enviar salida, verificar credenciales del canal. El
  dominio y la aplicación dependen solo de ese puerto.
- Cada canal es un paquete propio:
  `conversation_gateway/infrastructure/channels/whatsapp/`,
  `.../instagram/`, `.../messenger/`, con su adaptador de payload y su cliente de envío.
- El webhook único de `conversation_gateway` hace la verificación y la firma comunes,
  y delega al adaptador del canal la interpretación del mensaje antes de encolarlo.
- El tenant se resuelve una sola vez, igual para los tres canales (ADR 0003).
- **Añadir un canal = un paquete nuevo bajo
  `conversation_gateway/infrastructure/channels/`** y su registro en el mapeo de
  adaptadores; **no se toca el dominio ni el grafo**.
- Si la adición requiere un tipo de mensaje que el dominio no modela, se añade al
  contrato correspondiente (ADR 0005) en el mismo PR.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
| --- | --- | --- | --- |
| Código condicional por canal dentro de un solo módulo (`if canal == "whatsapp"`) | Un solo archivo que se ve entero; sin interfaces que mantener. | Crece linealmente con los canales; cada canal condiciona a todos los demás; probar un canal exige ejecutar los caminos de los otros. | Se descarta por complejidad creciente y por hacer que un cambio de un canal pueda romper a otro. |
| Un slice por canal (`whatsapp_gateway`, `instagram_gateway`, ...) | Encaje perfecto con el slicing vertical. | Duplicaría verificación, firma, SQS, resolución de tenant y lógica de respuesta en tres sitios; los fixes se aplicarían tres veces. | Se descarta por duplicación: lo común es mayor que lo específico. |
| Delegar la unificación en una herramienta externa de agregación de canales | Cero código propio de adaptadores. | Añade un proveedor y su coste; escasa visibilidad del payload; no resuelve la frontera interna de dominio. | Se descarta: el sistema necesita control del formato y de la verificación. |

## Consecuencias

### Positivas

- El dominio de conversación es agnóstico al canal: el grafo se prueba con un solo
  adaptador falso.
- Ampliar o corregir un canal queda confinado a su paquete.
- Verificación, firma, SQS y resolución de tenant se escriben una vez para los tres
  canales.
- El coste marginal de un canal nuevo es bajo y acotado.

### Negativas / riesgos

- Un puerto demasiado amplio obligaría a que todos los adaptadores implementen lo que no
  usan; hay que mantenerlo mínimo y evolucionarlo por contrato.
- Los tres canales de Meta evolucionan de forma independiente: un cambio de payload de
  Instagram no afecta a WhatsApp, pero sí obliga a mantener tres adaptadores.
- Un error en la capa común de verificación afecta a los tres canales a la vez: exige
  tests que recorran los tres adaptadores.
- Sigue habiendo que mantener credenciales por canal y por comercio, que deben
  resolverse fuera del código: nunca en el repositorio.

## Relacionados

- [0003. Multi-tenancy: tenant resuelto en el gateway](0003-multi-tenancy-tenant-en-gateway.md)
- [0005. Comunicación entre slices vía contracts](0005-comunicacion-entre-slices-via-contracts.md)
- [0006. Reemplazo gradual del backend legacy](0006-reemplazo-gradual-del-backend-legacy.md)
- [Visión general de la arquitectura](../architecture/OVERVIEW.md)
- [Guía para agentes del repositorio](../../AGENTS.md)
