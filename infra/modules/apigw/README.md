# Módulo: apigw

API Gateway **HTTP (v2)** con el webhook de Meta: `GET /webhook` (verificación
`hub.challenge`) y `POST /webhook` (mensajes). **Paso 6.**

## Recursos

- `aws_apigatewayv2_api`, stage `$default` con auto-deploy y access logs JSON
  (`$context`) a CloudWatch con retención, integración `AWS_PROXY` por ruta y
  `aws_lambda_permission` **concreto por ruta** (nunca `*`).

## Variables

| Nombre | Descripción |
| --- | --- |
| `name` | Nombre de la API (p. ej. `chatbot-aws-dev`). |
| `environment` | Entorno (aparece en el nombre del stage/log group). |
| `functions` | Mapa nombre → `invoke_arns` (salida del módulo `lambda`). |
| `routes` | Mapa: clave → `method`, `path`, `function`. |
| `log_retention_days` | Retención de access logs (default 30). |

## Salidas

`api_endpoint` (URL base del webhook → Paso 9), `api_id`.

## Notas

Rate limiting, validación de la firma de Meta y rutas internas por canal llegan
con el Paso 9.
