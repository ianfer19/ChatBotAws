# Backend remoto: el estado de este entorno vive en S3 con lock en DynamoDB
# (recursos creados una única vez por infra/bootstrap/).
#
# El bloque va vacío a propósito: la configuración completa está en
# `backend.hcl` y se inyecta en el init con:
#
#     terraform init -backend-config=backend.hcl
#
# CI usa `init -backend=false`, que ignora este bloque por completo, así que
# validar nunca requiere credenciales ni el backend desplegado.
terraform {
  backend "s3" {}
}
