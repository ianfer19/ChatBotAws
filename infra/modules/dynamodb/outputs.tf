output "table_names" {
  description = "Mapa nombre lógico → nombre real de cada tabla creada en el entorno."
  value       = { for nombre, tabla in aws_dynamodb_table.tabla : nombre => tabla.name }
}
