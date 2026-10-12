# Entorno: prod

Stack de producción: cifrado KMS con rotación, Aurora 1–2 ACU con protección de
borrado y snapshot final obligatorio, retención de logs conforme al ADR 0007 y
alarmas (observability → Paso 13). **Paso 6.**

Módulos cableados: `kms`, `network`, `s3`, `dynamodb`, `sqs` (cola de eventos +
DLQ del gateway, Paso 9), `aurora`, `iam`, `lambda` (`conversation_gateway` y
`consumer`) y `apigw` (`/webhook`). El zip es único (`artifacts/chatbot.zip`,
generado por `scripts/package_lambda.py`); la Lambda `supervisor` se retiró
porque no tenía handler real (el grafo corre in-process en el consumer; vuelve
con el Paso 10). Sin `conversation_admin` en prod (decisión 1, alto de canales
vía el legacy).

## Uso

```powershell
terraform -chdir=infra/envs/prod init -backend-config=backend.hcl   # una vez, con credenciales
terraform -chdir=infra/envs/prod plan      # revisar siempre antes del apply
terraform -chdir=infra/envs/prod apply
```

Sin credenciales (solo validación, como en CI):

```powershell
terraform -chdir=infra/envs/prod init -backend=false
terraform -chdir=infra/envs/prod validate
```

Estado por entorno: clave `envs/prod/terraform.tfstate` en el bucket
compartido (ADR 0012). Destruir este stack exige revisión: `deletion_protection`
está activo en Aurora.
