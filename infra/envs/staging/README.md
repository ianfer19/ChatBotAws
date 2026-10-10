# Entorno: staging

Stack de pruebas con un comercio real piloto: misma forma que `dev` (Aurora
0.5–1 ACU, sin protección de borrado) pero con datos sembrados y cuentas de
Meta no productivas. **Paso 6.**

Módulos cableados: `kms`, `network`, `s3`, `dynamodb`, `sqs` (cola de eventos +
DLQ del gateway, Paso 9), `aurora`, `iam`, `lambda` (`conversation_gateway`,
`supervisor`) y `apigw` (`/webhook`).

## Uso

```powershell
terraform -chdir=infra/envs/staging init -backend-config=backend.hcl   # una vez, con credenciales
terraform -chdir=infra/envs/staging plan
terraform -chdir=infra/envs/staging apply
```

Sin credenciales (solo validación, como en CI):

```powershell
terraform -chdir=infra/envs/staging init -backend=false
terraform -chdir=infra/envs/staging validate
```

Estado por entorno: clave `envs/staging/terraform.tfstate` en el bucket
compartido (ADR 0012); `backend.hcl` ya apunta a él.
