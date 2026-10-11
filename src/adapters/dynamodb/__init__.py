"""Adapter de DynamoDB para las tablas operacionales del chatbot con aislamiento por
tenant. Paso 6. Desde el Paso 8 expone `DynamoDBMemoryStore`, el `MemoryStorePort`
real detrás del checkpointer de conversación (tabla `chatbot_checkpoints`). Desde el
Paso 9 (Fase 6) expone `DynamoConversationStore` para la tabla `chatbot_conversations`
(ventana de historial del consumer).
"""

from adapters.dynamodb.conversations import DynamoConversationStore, TablaConversaciones
from adapters.dynamodb.memory import DynamoDBClient, DynamoDBMemoryStore

__all__ = [
    "DynamoConversationStore",
    "DynamoDBClient",
    "DynamoDBMemoryStore",
    "TablaConversaciones",
]
