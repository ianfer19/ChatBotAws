# Tests de integración

Pruebas contra servicios reales de AWS (Bedrock desde el **Paso 2**; DynamoDB, S3 y
localstack desde el **Paso 6**). Corren con credenciales de dev: llevan el marker
`integration` y en CI se omiten (sin credenciales no hay con qué firmar). **Pasos 2 y 6+.**

Para ver el motivo de cada omisión: `pytest tests/integration -rs`.

## Smoke de Bedrock (Paso 2)

`test_bedrock_smoke.py` construye `BedrockLLM` con `Settings` y le hace una invocación real
de un solo mensaje (coste despreciable, `TODO(verify pricing)` en el Paso 14). Cuenta de
desarrollo **con acceso a Bedrock verificado**: `iastock-old` (us-east-1).

```powershell
$env:AWS_PROFILE = "iastock-old"                     # cuenta con acceso a Bedrock
$env:AWS_DEFAULT_REGION = "us-east-1"                # botocore lee esta variable (no AWS_REGION)
$env:CHATBOT_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
pytest tests/integration/test_bedrock_smoke.py -v -rs
```

Verificado el 2026-10-08: `1 passed`.

### Cuentas y acceso a modelos

- `iastock-old`: acceso verificado; el smoke pasa.
- `iastock-administrator`: tiene `bedrock:InvokeModel` (AdministratorAccess), pero Bedrock
  responde «Your account is currently being verified» / «Operation not allowed»: la cuenta
  está **pendiente de verificación** de AWS. Mientras eso dure, el smoke con ese perfil se
  **omite** con ese motivo. No existe API de Bedrock para consultar ni aceptar el acceso
  (comprobado en las 57 operaciones del servicio): se gestiona en la consola →
  Amazon Bedrock → *Model access*.
- Otro motivo de omisión: sin `AWS_DEFAULT_REGION` (botocore no lee `AWS_REGION`).

Si el error no es ninguno de los anteriores, el test **falla**: es un bug del código, no un
estado de la cuenta AWS.
