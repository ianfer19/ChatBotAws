# Red mínima: VPC + 2 subnets privadas en AZ distintas.
#
# Deliberadamente NO hay internet gateway, NAT ni subnets públicas: por defecto
# las Lambdas corren FUERA de VPC (SECURITY §6) y solo Aurora vive aquí, que no
# necesita salida a internet. Los VPC endpoints llegan cuando un recurso dentro
# de la VPC justifique su costo fijo frente a la alternativa → TODO(verify).

data "aws_availability_zones" "available" {}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.name_prefix}-vpc"
  }
}

resource "aws_subnet" "privadas" {
  count = 2

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.name_prefix}-privada-${count.index}"
    Tier = "private"
  }
}

# Una sola tabla de rutas privada: solo la ruta local de la VPC (sin NAT).
resource "aws_route_table" "privada" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.name_prefix}-privada"
  }
}

resource "aws_route_table_association" "privadas" {
  count = length(aws_subnet.privadas)

  subnet_id      = aws_subnet.privadas[count.index].id
  route_table_id = aws_route_table.privada.id
}
