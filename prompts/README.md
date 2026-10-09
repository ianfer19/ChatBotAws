# Prompts

Espejo **local** de los prompts de Bedrock Prompt Management (la fuente de verdad en
runtime es Prompt Management; ver [docs/ai/PROMPT_MANAGEMENT.md](../docs/ai/PROMPT_MANAGEMENT.md)).

```
prompts/
├── base/                # Plantillas canónicas compartidas por todos los tenants
│   ├── README.md
│   ├── supervisor.md    # Clasificador de intención (Paso 4; lo carga application/prompts.py)
│   └── appointments.md  # Asistente de citas (Paso 3; lo carga application/prompts.py)
└── tenants/
    └── _example/        # Ejemplo de estructura por comercio (plantilla a copiar)
        ├── README.md
        └── system.md
```

## Reglas

1. **Naming**: `<agente>.md` (`system`, `greeting`, `sales`, `appointments`, `orders`,
   `fallback`, `handoff`).
2. **Variables** entre llaves `{comercio}`, `{horario}`, `{tono}`… — siempre validadas por
   Pydantic antes de renderizar; sin PII ni secretos dentro del prompt.
3. **Cambios**: toda modificación de `base/` exige pasar los evals
   ([docs/ai/EVALUATION.md](../docs/ai/EVALUATION.md)) y dejar nota en el changelog del prompt.
4. **Tenants reales nunca se commitean**: solo `_example/` vive en git; los prompts por
   comercio se publican en Prompt Management (fuera de la ruta, `tenant_prompts`, ver ROADMAP §4).
5. Versionado semántico (`v1.2.0`) con rollback en Prompt Management (`TODO(verify)` del
   procedimiento exacto).

Estado: plantillas locales (Fases 1–2); `base/appointments.md` existe desde el **Paso 3**
(y lo carga `slices/appointments/application/prompts.py`) y `base/supervisor.md` desde el
**Paso 4** (lo carga `slices/supervisor/application/prompts.py`); el resto de prompts se
define con los agentes (Pasos 5+).
