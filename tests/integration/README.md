# Tests de integración

Pruebas contra servicios reales de AWS (Bedrock desde el **Paso 2**; DynamoDB, S3 y
localstack desde el **Paso 6**). Corren con credenciales de dev: llevan el marker
`integration` y en CI se omiten (sin credenciales no hay con qué firmar). **Pasos 2 y 6+.**

Para ver el motivo de cada omisión: `pytest tests/integration -rs`.

## Smoke de Bedrock (Paso 2)

`test_bedrock_smoke.py` construye `BedrockLLM` con `Settings` y le hace una invocación real
de un solo mensaje (coste despreciable, `TODO(verify pricing)` en el Paso 14):

```powershell
$env:AWS_PROFILE = "iastock-administrator"        # credenciales de dev
$env:AWS_DEFAULT_REGION = "us-east-1"             # botocore lee esta variable (no AWS_REGION)
$env:CHATBOT_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
pytest tests/integration/test_bedrock_smoke.py -v -rs
```

Si la cuenta todavía no tiene verificado el acceso a modelos de Bedrock (Bedrock responde
«Operation not allowed» o «account is currently being verified»), el test se **omite** con
ese motivo en vez de fallar: es un estado de la cuenta AWS, no un bug del código. Cualquier
otro error sí falla el test.
