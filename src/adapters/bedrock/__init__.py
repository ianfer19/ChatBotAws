"""Adapter de Amazon Bedrock: `LLMPort` sobre Converse, embeddings y Guardrails (Paso 13).

Solo se exportan las piezas públicas: `BedrockLLM` y `BedrockEmbeddings` (los
adapters) y los Protocolos mínimos que hay que inyectar en tests.
"""

from adapters.bedrock.embeddings import BedrockEmbeddings, InvokeModelClient
from adapters.bedrock.llm import BedrockLLM, ConverseClient

__all__ = ["BedrockEmbeddings", "BedrockLLM", "ConverseClient", "InvokeModelClient"]
