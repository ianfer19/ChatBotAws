# Módulo: iam

Rol IAM por función Lambda con least-privilege; sin permisos amplios
hardcodeados. **Paso 6.**

## Recursos

- `aws_iam_role` (confianza `lambda.amazonaws.com`), adjunto de
  `AWSLambdaBasicExecutionRole` y `aws_iam_role_policy` **inline por función**:
  cada entrada de `inline_policies` añade solo sus permisos (hoy
  `bedrock:InvokeModel*` exclusivamente para `supervisor`).

## Variables

| Nombre | Descripción |
| --- | --- |
| `environment` | Entorno (aparece en el nombre del rol). |
| `functions` | Set de nombres de funciones que reciben un rol. |
| `inline_policies` | Mapa función → JSON de política adicional (opcional). |

## Salidas

`role_arns` — los consume el módulo `lambda`.

ARNs exactos de Bedrock → `TODO(verify)` al cablear el adapter (Pasos 7–10).
