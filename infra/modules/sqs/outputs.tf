output "queue_url" {
  description = "URL de la cola de eventos (envío); la usa la Lambda del webhook."
  value       = aws_sqs_queue.events.url
}

output "queue_arn" {
  description = "ARN de la cola de eventos (recepción y permisos)."
  value       = aws_sqs_queue.events.arn
}

output "dlq_url" {
  description = "URL de la DLQ para inspección de mensajes tóxicos (runbooks)."
  value       = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  description = "ARN de la DLQ (permisos de redrive y alertas)."
  value       = aws_sqs_queue.dlq.arn
}
