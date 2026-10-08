# Arquitectura hexagonal y vertical slicing

Documento de la Fase 1. Define las reglas de dependencia que rigen todo el código de
`src/` y cómo se verifican automáticamente. Registro asociado:
[ADR 0001](../adr/0001-arquitectura-hexagonal-y-vertical-slicing.md).

## Qué es arquitectura hexagonal aquí

El núcleo de negocio no conoce AWS, HTTP ni frameworks. Se expone mediante **puertos**
(interfases tipadas) y se conecta al mundo exterior mediante **adaptadores**:

- **Puertos** en `domain/` (interfaces que implementan los adaptadores de salida, p. ej.
  `ChannelPort`, `LLMPort`) y en `application/` (interfaces de entrada o de casos de uso).
- **Adaptadores** en `infrastructure/` dentro de cada slice (detalles concretos: webhook,
  firma, repositorios) y en `src/adapters/` (servicios AWS: bedrock, agentcore, dynamodb,
  aurora, s3, comprehend, legacy_backend).
- **`handler/` es la composition root**: el único lugar que instancia adaptadores y los
  inyecta en los casos de uso. Fuera de ahí no se construyen clientes AWS ni se leen
  variables de entorno para conectarse a servicios.

El "hexágono" es la forma en que el dominio queda a resguardo: entran llamadas (handlers)
y salen efectos (adaptadores), pero el centro no se entera de ninguno de los dos.

## Las cuatro reglas de dependencia

1. `handler → application → domain`: el handler compone casos de uso; los casos de uso
   usan el dominio. Nunca al revés.
2. `infrastructure → domain`: los adaptadores implementan puertos del dominio y pueden
   depender del dominio y de `shared/`, de nada más dentro del slice.
3. El dominio no importa nada externo salvo `stdlib`, `pydantic` y `shared/`: sin boto3, sin
   SQLAlchemy, sin LangChain, sin HTTP, sin logging de terceros.
4. Los slices no se importan entre sí: se comunican únicamente por `shared/contracts`.

Nota: como la regla 2 exige `infrastructure → domain`, los puertos que los adaptadores
implementan se declaran en `domain/`; los puertos de entrada del slice se declaran en
`application/` y solo los consume `handler`.

## Cómo se verifican las reglas

| Mecanismo | Qué comprueba | Dónde |
|---|---|---|
| import-linter | Contratos de importación: `handler → application → domain`, `infrastructure → domain`, dominio aislado, aislamiento entre slices | configuración en `pyproject.toml` |
| Test estructural | Que existan `domain/`, `application/`, `infrastructure/` y `handler/` por slice, y que ningún archivo de `domain/` importe paquetes prohibidos | `tests/unit/` |
| CI | Ambos mecanismos corren en cada PR y bloquean el merge | `.github/workflows/` |

Si import-linter falla, la corrección es mover la dependencia, no relajar el contrato.

## Árbol de un slice (ejemplo: `conversation_gateway`)

```text
src/slices/conversation_gateway/
├── AGENTS.md                  # reglas y comandos del slice
├── domain/
│   ├── entities.py            # mensaje entrante, evento de canal
│   ├── events.py              # eventos de dominio (p. ej. mensajeValidado)
│   └── ports.py               # ChannelPort y puertos de salida
├── application/
│   ├── use_cases.py           # verificar_webhook, encolar_mensaje
│   └── services.py            # orquestación entre puertos del dominio
├── infrastructure/
│   ├── webhook_meta.py        # hub.challenge, X-Hub-Signature-256
│   └── channels/              # adapters WhatsApp, Instagram, Messenger
└── handler/
    └── lambda_webhook.py      # composition root de este slice
```

Las reglas aplicadas al árbol: `handler` importa `application` e `infrastructure`;
`application` importa `domain`; `infrastructure` importa `domain`; `domain` no importa
ninguno de los otros tres.

## Vertical slicing

Un slice es una **feature de punta a punta** en una sola carpeta: desde la entrada
(handler) hasta las reglas de negocio (domain) y los efectos externos (infrastructure).
Vertical significa que no hay capas horizontales compartidas entre features: para cambiar
cómo se saluda, se trabaja dentro de `supervisor/`; para cambiar cómo se archiva, dentro de
`retention_archiving/`.

Lo que sí se comparte es el kernel (`src/shared/`) y los adaptadores de plataforma
(`src/adapters/`), que son infraestructura común, no funcionalidad de negocio.

## DI ligera y por qué el handler compone

No se usa framework de inyección de dependencias. El handler recibe la configuración del
entorno, construye los adaptadores concretos y se los pasa por parámetro a los casos de
uso:

```python
def lambda_handler(event, _context):
    cfg = load_config()
    repo = DynamoConversationRepo(cfg)          # adaptador concreto
    graph = build_graph(repo, BedrockLLM(cfg))  # puertos ya inyectados
    return graph.invoke(parse(event))
```

Al no ocultar la composición, el test puede sustituir cualquier adaptador por un doble en
una línea, y el flujo de datos es legible de arriba abajo. Las alternativas (container,
decorators mágicos) añaden indirección sin ganar nada a este tamaño de sistema.

## Cómo agregar un slice

1. Crear `src/slices/<nombre>/` con `domain/`, `application/`, `infrastructure/`,
   `handler/` y `AGENTS.md`.
2. Definir primero las entidades y reglas en `domain/`; después los casos de uso en
   `application/`; al final los adaptadores y el handler.
3. Si el slice necesita hablar con otro, declarar el mensaje en `shared/contracts/`; jamás
   importar el otro slice.
4. Añadir el contrato de importación si el slice introduce una nueva dependencia nueva.
5. Añadir tests `unit` (dominio), `contract` (contratos) e `integration` (adaptadores).

El procedimiento detallado y la checklist viven en [`src/slices/AGENTS.md`](../../src/slices/AGENTS.md).

## Ejemplo real: por qué "no modificar la hora de un pedido" se resuelve en `domain/`

Un usuario escribe "cambia mi pedido a las 8 pm". Si la regla viviera en el prompt, basta
con un ataque de prompt injection o con que el modelo alucine para saltársela. Por eso la
misma prohibición existe en cinco capas independientes:

1. **Tool inexistente**: `orders` no expone ninguna tool de modificación de horario al
   LLM; el modelo ni siquiera puede intentarlo.
2. **Dominio**: `orders/domain` tiene un método que rechaza el cambio de `Order.scheduled_at`
   con un error tipado; cualquier camino que llegue ahí muere.
3. **AgentCore Policy**: la política del tenant deniega la acción aunque un adaptador la
   invoque.
4. **Guardrails**: el tema "modificar hora de pedidos" está denegado; la respuesta bloqueada
   genera fallback y log con `correlation_id`.
5. **Regresión**: un test en `tests/unit/` y una eval en `tests/agent_evals/` fallan si
   alguna capa se abre.

Capas 1, 2 y 5 son código de este repo (aplicables ya en la Fase 2 y en los Pasos 1–7); la capa 4
(Guardrails) se activa en el Paso 13 y la 3 (AgentCore Policy) en los Pasos 11–12. El patrón
general es el mismo para precios, stock, disponibilidad y estados de pedido: primero el
dominio, después el modelo.
