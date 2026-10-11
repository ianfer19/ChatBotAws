# 0014. Composition root de producción en `src/handlers/`

- **Estado:** Aceptado
- **Fecha:** 2026-10-10
- **Decisores:** Plataforma ChatBotAws

## Contexto

El pipeline del Conversation gateway (Paso 9, Fase 6) es
`SQS → consumer → supervisor → respuesta al canal`. Ese flujo necesita, en una sola
pieza de ejecución, adaptadores de **varios** slices a la vez: el supervisor
(`supervisor`), el canal de salida (`conversation_gateway`) y los stores/LLM
(`adapters`). La regla de dependencia del repo prohíbe que un slice importe a otro
(§3 de `AGENTS.md`; verificado en CI por `import-linter` y por el test AST
`tests/unit/test_repo_contract.py`, que solo cubre `src/slices/`). Además,
`infrastructure` solo puede depender de `domain` (ADR 0001).

Sin un lugar explícito para esa composición, el wiring del consumer tendría que vivir
dentro de un slice (rompiendo el aislamiento) o duplicarse en varios.

## Decisión

Creamos el paquete top-level **`src/handlers/`** como **composition root de
producción**: el único lugar del repo que puede importar varios slices a la vez.

Implicaciones:

1. `src/handlers/consumer.py` compone el grafo del supervisor con `MetaChannel`,
   `BedrockLLM` y `DynamoConversationStore`; es el espejo productivo de
   `scripts/chat_citas.py` (mismo patrón de composición, sobre adaptadores reales).
2. El test de aislamiento AST (`test_repo_contract.py`) **solo cubre `src/slices/`**;
   `src/handlers/` queda fuera de ese test por diseño.
3. `import-linter` registra `handlers` como contenedor en `pyproject.toml`
   (`root_packages`), de modo que las capas internas de un slice siguen verificándose
   pero el paquete de composición puede importar slices.
4. Los `handler` de Lambda de cada entorno importan `handlers.consumer.main`
   (`infra/envs/*/main.tf`).
5. La webhook y el admin del gateway **no** viven aquí: siguen en
   `src/slices/conversation_gateway/handler/` porque componen un solo slice.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas | Por qué se descartó |
|---|---|---|---|
| Handler de composición dentro de un slice (p. ej. `supervisor/handler/`) | Sin paquete nuevo | Un slice importaría a otro slice: viola §3 y `lint-imports` | Rompe el aislamiento entre slices (ADR 0005) |
| "Meta-slice" que orquesta a los demás | Reutilizable como slice | Los slices no pueden importarse entre sí; un meta-slice solo sería un slice que importa a todos | Mismo problema de aislamiento, con más ceremonia |
| Composición en `infrastructure/` de cada slice | Cada slice se arma solo | `infrastructure` solo depende de `domain` (ADR 0001); no puede ver `application` de otro slice | Imposible sin romper la regla de dependencia |
| Glue en `scripts/` (como el REPL) | Ya existe un patrón | `scripts/` no es código de producción desplegable; no tiene tests ni entra en CI como Lambda | Sirve para pruebas manuales, no para el runtime |

## Consecuencias

### Positivas

- Un único punto de composición documentado y testeable (con dobles, sin AWS).
- El aislamiento entre slices se mantiene intacto: la excepción está acotada,
  nombrada y verificada (`lint-imports`).
- Commit C (especialistas + contexto real) será un cambio aditivo en
  `_construir_consumer`, sin reabrir la decisión.

### Negativas / riesgos

- `src/handlers/` puede degradarse en un "cubo de maridre" si no se le exige
  docstrings, tipos y tests como al resto (se mitiga con la misma batería de CI).
- El test AST de aislamiento no cubre este paquete: si alguien moviera imports
  prohibidos dentro de `src/handlers/`, solo `lint-imports` lo pillaría. Se asume
  aceptable porque el paquete está deliberadamente fuera del perímetro de slices.

## Relacionados

- [ADR 0010](0010-composicion-de-grafos-por-invocacion.md) — el supervisor invoca a
  los especialistas por invocación tras un port; este ADR complementa dónde se cablea
  esa composición en producción.
- [ADR 0005](0005-comunicacion-entre-slices-via-contracts.md) — comunicación entre
  slices solo por contracts.
- [ADR 0009](0009-channelport-unico-canales-meta.md) — un único `ChannelPort`.
- `docs/progress/paso-9-conversation-gateway.md` — checklist vivo del Paso 9.
