"""Adapter de Amazon Bedrock: `LLMPort` sobre Converse y, más adelante, Guardrails (Paso 13).

Solo se exportan las piezas públicas: `BedrockLLM` (el adapter) y `ConverseClient`
(el Protocolo mínimo que hay que inyectar en tests).
"""

from adapters.bedrock.llm import BedrockLLM, ConverseClient

__all__ = ["BedrockLLM", "ConverseClient"]
