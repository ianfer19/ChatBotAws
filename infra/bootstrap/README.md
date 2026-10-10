# Bootstrap del estado remoto

Crea el **S3 de estado** y la **tabla de lock DynamoDB** que después usan los
backends de `infra/envs/*`. Es el paso «chicken-egg» de Terraform: el estado no
puede guardarse a sí mismo, así que este directorio vive con backend local.

## Una sola vez, con credenciales

```powershell
cd infra\bootstrap
terraform init
terraform apply
```

Tras el apply los outputs confirman los nombres (`state_bucket_name`,
`lock_table_name`), que ya están escritos en `infra/envs/<env>/backend.hcl`.
Si el perfil apunta a otra cuenta, actualiza esos `backend.hcl`.

## Notas

- `terraform.tfstate` de este directorio está gitignorado: es el único state
  que vive en local y solo existe hasta que se aplica esto.
- CI (`terraform.yml`) y `make tf-validate` ejecutan `init -backend=false` +
  `validate` aquí y en cada entorno; **nunca** aplican ni necesitan credenciales.
- Costo: < 1 USD/mes (`TODO(verify pricing)`).
- `TODO(verify)`: rol mínimo de CI/CD (`role_terraform_ci` de
  `docs/security/SECURITY.md` §6) para que GitHub Actions aplique en el futuro.
