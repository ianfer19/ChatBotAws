# Tests

| Carpeta | Qué cubre | Paso |
|---|---|---|
| `unit/` | Dominio puro, utilidades del kernel y **estructura del repo** (`test_repo_contract.py`) | 1+ |
| `integration/` | Adaptadores contra servicios reales o localstack (requiere credenciales de dev) | 6+ |
| `contract/` | Esquemas de `shared/contracts/` y contrato con el backend legacy | 3+ |
| `agent_evals/` | Comportamiento conversacional con datasets (ver su `README.md`) | 14 |

```powershell
pytest                          # todo
pytest tests/unit -v            # solo unidades (rápido, sin AWS)
pytest tests/unit/test_repo_contract.py   # reglas de estructura/dependencia
```

Reglas: datos sintéticos siempre; ningún test necesita secretos reales; los tests de
`integration/` se omiten sin credenciales (marcador futuro `integration`, `TODO(verify)`).
