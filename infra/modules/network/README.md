# Módulo: network

VPC mínima de trabajo: **solo subnets privadas; sin NAT, sin IGW y sin VPC
endpoints** por defecto. Las Lambdas no viven en la VPC y Aurora no necesita
salida a internet (SECURITY §6, ADR 0012). **Paso 6.**

## Recursos

- `aws_vpc`, 2 `aws_subnet` privadas en AZ distintas, 1 route table privada y
  sus asociaciones.

## Variables

| Nombre | Descripción |
| --- | --- |
| `name_prefix` | Prefijo de nombres (p. ej. `chatbot-aws-dev`). |
| `vpc_cidr` | CIDR de la VPC (dev `10.10.0.0/16`, staging `10.20.0.0/16`, prod `10.30.0.0/16`). |

## Salidas

`vpc_id`, `vpc_cidr` (origen único permitido al 5432 de Aurora) y
`private_subnet_ids`.

## Notas

VPC endpoints y NAT quedan `TODO(verify)` hasta que un recurso interno lo
justifique.
