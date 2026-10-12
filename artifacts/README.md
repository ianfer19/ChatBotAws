# Artefactos de Lambda

Desplegable de las funciones Lambda del Paso 9: **un único `chatbot.zip`**
(compartido por `conversation_gateway`, `conversation_admin` y `consumer`;
solo cambia el `handler` de cada una). **Nunca se commitea**: este directorio
solo contiene este README y el `.zip` construido en local o en CI.

```powershell
# Construir el zip (código src/ + dependencias de runtime; ver el docstring)
python scripts\package_lambda.py          # → artifacts\chatbot.zip
# o con otra ruta de salida:
python scripts\package_lambda.py --out ruta\otro.zip
```

El script copia `src/{shared,adapters,slices,handlers}` tal cual (raíz del zip
= raíz de importación de los `handler` de Terraform) e instala
`langgraph`/`requests`/`pydantic`/`pydantic-settings` con `pip install --target`.
Sin `boto3` (lo trae el runtime de Lambda) y sin `psycopg` (Aurora no se usa en
estas funciones).

`infra/modules/lambda` lee la ruta con `filebase64sha256` envuelto en `try()`,
así que `terraform validate` pasa sin el zip; `terraform apply` lo exige →
correr el script antes de aplicar (runbook:
`docs/runbooks/DESPLIEGUE_DEV.md`).
