"""Adapter de DynamoDB para las tablas operacionales del chatbot con aislamiento por
tenant. Paso 6. Desde el Paso 8 expone `DynamoDBMemoryStore`, el `MemoryStorePort`
real detrás del checkpointer de conversación (tabla `chatbot_checkpoints`).
"""

from adapters.dynamodb.memory import DynamoDBClient, DynamoDBMemoryStore

__all__ = ["DynamoDBClient", "DynamoDBMemoryStore"]
