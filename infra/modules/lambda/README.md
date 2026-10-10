# Módulo: lambda

Factory de funciones Lambda **Python 3.12**, una por punto de entrada (hoy
`conversation_gateway` y `supervisor`). **Paso 6.**

## Recursos

- Grupo de logs por función con retención configurable (se crea **antes** que la
  función) y `aws_lambda_function` con `source_code_hash`
  (`try(filebase64sha256(zip_path))`) para validar sin artefactos.

## Variables

| Nombre | Descripción |
| --- | --- |
| `environment` | Entorno (aparece en el nombre de la función). |
| `functions` | Mapa: nombre → `handler`, `zip_path`, `timeout`, `memory_size`, `env`. |
| `role_arns` | Roles por función (salida del módulo `iam`). |
| `log_retention_days` | Retención de logs (default 30). |

## Salidas

`function_names`, `invoke_arns` — los consume el módulo `apigw`.

## Notas

Los zips viven en `artifacts/*.zip` (gitignoreados salvo su README); el
empaquetado real llega en el Paso 9 (`TODO(verify)`).
