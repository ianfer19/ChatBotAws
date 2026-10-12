# Entorno: dev

Stack de desarrollo: datos sintéticos, cuentas de prueba de Meta y el menor
costo posible (Aurora 0.5–1 ACU, sin protección de borrado, snapshot final
omitido). **Paso 6.**

Módulos cableados: `kms`, `network`, `s3`, `dynamodb`, `sqs` (cola de eventos +
DLQ del gateway, Paso 9), `aurora`, `iam`, `lambda` (`conversation_gateway`,
`conversation_admin` —alta de canales con `-var admin_token=…`, solo dev/staging—
y `consumer`) y `apigw` (`/webhook` y `POST /admin/channels`). El zip de las tres
funciones es único (`artifacts/chatbot.zip`, generado por `scripts/package_lambda.py`);
la Lambda `supervisor` se retiró porque no tenía handler real (el grafo corre
in-process en el consumer; vuelve con el Paso 10).

## Uso

```powershell
# 0) Generar el desplegable (una vez por cambio de código; ver docs/runbooks/DESPLIEGUE_DEV.md)
python scripts\package_lambda.py

# 1) Credenciales AWS + estado remoto (una vez)
terraform -chdir=infra/envs/dev init -backend-config=backend.hcl

# 2) Secretos del webhook y token del admin (no van al estado; pasar a mano)
terraform -chdir=infra/envs/dev apply `
  -var "admin_token=<ADMIN_TOKEN_DEV>" `
  -var "webhook_verify_token=<VERIFY_TOKEN_META>" `
  -var "meta_app_secret=<APP_SECRET_META>"
```

Sin credenciales (solo validación, como en CI):

```powershell
terraform -chdir=infra/envs/dev init -backend=false
terraform -chdir=infra/envs/dev validate
```

El bucket de estado y el lock se crean antes con `infra/bootstrap/`
(ver `infra/README.md`). Estado por entorno: clave `envs/dev/terraform.tfstate`
(ADR 0012).
