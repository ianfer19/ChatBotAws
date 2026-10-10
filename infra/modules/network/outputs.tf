output "vpc_id" {
  description = "ID de la VPC del entorno."
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "IDs de las 2 subnets privadas (dónde vive Aurora)."
  value       = aws_subnet.privadas[*].id
}
