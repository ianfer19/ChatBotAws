"""Adapter de SQS: `SQSEventBus`, la cola de entrada al pipeline (Paso 9).

Implementa `shared.ports.EventBusPort` sobre SQS con DLQ (infra/modules/sqs);
errores tipados, timeout y sin loguear payloads con PII.
"""

from adapters.sqs.event_bus import ColaSQS, SQSEventBus

__all__ = ["ColaSQS", "SQSEventBus"]
