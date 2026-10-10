# Entorno: dev

Stack de desarrollo: datos sintéticos, cuentas de prueba de Meta y el menor
costo posible (Aurora 0.5–1 ACU, sin protección de borrado, snapshot final
omitido). **Paso 6.**

Módulos cableados: `kms`, `network`, `s3`, `dynamodb`, `aurora`, `iam`,
`lambda` (`conversation_gateway`, `supervisor`) y `apigw` (`/webhook`).

## Uso

```powershell
terraform -chdir=infra/envs/dev init -backend-config=backend.hcl   # una vez, con credenciales
terraform -chdir=infra/envs/dev plan
terraform -chdir=infra/envs/dev apply
```

Sin credenciales (solo validación, como en CI):

```powershell
terraform -chdir=infra/envs/dev init -backend=false
terraform -chdir=infra/envs/dev validate
```

El bucket de estado y el lock se crean antes con `infra/bootstrap/`
(ver `infra/README.md`). Estado por entorno: clave `envs/dev/terraform.tfstate`
(ADR 0012).
