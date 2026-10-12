# DESPLIEGUE_DEV

- **Paso:** 9 · **Estado:** Pendiente (no probado aún; el estado pasa a `Aprobado` cuando se ejecute una vez en dev con tráfico real de los 3 canales)
- **Última prueba:** sin probar

## Señales / disparador

- Primera puesta en marcha del entorno `dev` (nunca desplegado desde esta máquina) o
  despliegue tras un cambio de código que toca el gateway (`conversation_gateway`),
  el consumer o la infraestructura de los tres (`infra/envs/dev`, `scripts/package_lambda.py`).
- Tráfico real de WhatsApp/Instagram/Messenger todavía no llega al sistema: el webhook
  de Meta no está apuntando a API Gateway o el `terraform apply` no se ejecutó con los
  secretos correctos.

## Prerequisitos

- Credenciales AWS con permisos sobre la cuenta del backend (bucket
  `chatbot-aws-tfstate-029944900353`; `aws sts get-caller-identity` devuelve la cuenta
  esperada).
- Python 3.12 y `pip` accesibles (`python scripts\package_lambda.py` debe correr sin
  error antes de tocar Terraform).
- Terraform con el backend remoto ya inicializado (`init -backend-config=backend.hcl`
  en `infra/envs/dev`; si el estado está vacío o el bucket no existe, correr antes
  `infra/bootstrap/` — ver `infra/README.md`).
- Cuenta de Meta (app de desarrollo) con los permisos de WhatsApp Business Messaging,
  Instagram Messaging y Facebook Messenger; acceso a **Configuración de la app →
  Webhooks** para pegar la URL y el token de verificación.
- Tres valores a mano (no se committean nunca):
  - `ADMIN_TOKEN_DEV`: token propio que se usará en el `POST /admin/channels`.
  - `VERIFY_TOKEN_META`: token de verificación que se configurará en Meta (elegir uno
    opaco, p. ej. 32 bytes aleatorios).
  - `APP_SECRET_META`: secreto de la app Meta (para la firma `X-Hub-Signature-256`).

## Pasos

1. **Empaquetar el desplegable.** Desde la raíz del repo:

   ```powershell
   python scripts\package_lambda.py
   ```

   - Verificación: aparece `OK: ...\artifacts\chatbot.zip (NN.N MB comprimido)` y el
     archivo existe (`Get-Item artifacts\chatbot.zip`).

2. **Revisar el plan antes de aplicar.**

   ```powershell
   terraform -chdir=infra/envs/dev plan `
     -var "admin_token=$env:ADMIN_TOKEN_DEV" `
     -var "webhook_verify_token=$env:VERIFY_TOKEN_META" `
     -var "meta_app_secret=$env:APP_SECRET_META"
   ```

   - Verificación: el plan muestra exactamente tres funciones Lambda
     (`conversation_gateway`, `conversation_admin`, `consumer`), **sin** `supervisor`,
     con `zip = artifacts/chatbot.zip` y con las env vars
     `CHATBOT_WEBHOOK_VERIFY_TOKEN`/`CHATBOT_META_APP_SECRET` presentes en el gateway.
     Si aparece `supervisor` o rutas de zip viejas, el código de Terraform no es el
     esperado: abortar y revisar la rama.

3. **Aplicar.**

   ```powershell
   terraform -chdir=infra/envs/dev apply `
     -var "admin_token=$env:ADMIN_TOKEN_DEV" `
     -var "webhook_verify_token=$env:VERIFY_TOKEN_META" `
     -var "meta_app_secret=$env:APP_SECRET_META"
   ```

   - Verificación: `Apply complete!`; en la consola AWS (o con CLI) existen las tres
     Lambdas y el API Gateway `chatbot-aws-dev` con rutas `GET /webhook`,
     `POST /webhook` y `POST /admin/channels`.

4. **Registrar un canal de prueba (WhatsApp como primer canal).** El endpoint de admin
   solo existe en dev/staging (decisión 6):

   ```powershell
   $url = "<API_INVOKE_URL>/admin/channels"   # de la salida de `terraform output` o la consola
   Invoke-RestMethod -Method Post -Uri $url `
     -Headers @{ "x-admin-token" = $env:ADMIN_TOKEN_DEV } `
     -ContentType "application/json" `
     -Body (@{
       tenant_id   = "Sede_Elite_01"
       channel     = "whatsapp"
       channel_id  = "<PHONE_NUMBER_ID_META>"
       phone       = "<NUMERO_PRUEBA_E164>"
     } | ConvertTo-Json)
   ```

   - Verificación: la respuesta es `201`/`200` con el mapeo creado; verificar con un
     `GetItem` sobre `chatbot_channel_mapping` (PK
     `WA#<PHONE_NUMBER_ID>`, o consultar el código de `DynamoChannelMapping`) que la
     fila existe y apunta al tenant.

5. **Credenciales del canal en SSM.** El consumer las lee de
   `/sahagun/whatsapp/<tenant>/access_token` (SecureString). Crearlas a mano con el
   token de acceso de prueba de Meta:

   ```powershell
   aws ssm put-parameter --name "/sahagun/whatsapp/Sede_Elite_01/access_token" `
     --type SecureString --value "<ACCESS_TOKEN_META>"
   ```

   - Verificación: `aws ssm get-parameter --name ".../access_token" --with-decryption`
     devuelve el token.

6. **Configurar el webhook en Meta.** En la app de Meta → Webhooks:
   - Callback URL: `<API_INVOKE_URL>/webhook` (la misma del paso 4).
   - Verify token: exactamente el valor de `VERIFY_TOKEN_META` del paso 2.
   - Suscribir los campos de mensaje de WhatsApp/Instagram/Messenger.
   - Verificación: Meta acepta la verificación (el `GET /webhook` responde al
     `hub.challenge`; si falla, revisar los logs de la Lambda
     `conversation_gateway` en CloudWatch: el token no coincide).

7. **Probar el flujo end-to-end con tráfico real de los 3 canales.** Enviar un mensaje
   de prueba desde cada canal (WhatsApp al número de prueba; DM de Instagram; Messenger
   a la página de prueba) y verificar, por este orden:
   - El `POST /webhook` responde `200` (la firma HMAC pasó).
   - En CloudWatch del `conversation_gateway` hay un log con `correlation_id` y
     `tenant_id` (sin duplicados: la deduplicación funcionó).
   - En CloudWatch del `consumer` aparece el turno: supervisor clasificó, respondió y
     se envió la respuesta al canal (`MetaChannel.send` sin error).
   - El mensaje de respuesta **llega al cliente** en la app de WhatsApp/IG/Messenger.
   - Verificación: repetir el mismo mensaje dos veces y confirmar que solo genera un
     turno (deduplicación TTL 24 h).

8. **Limpiar la prueba (opcional).** Borrar el canal y el mensaje de prueba si no se
   van a conservar (p. ej. con `DeleteItem` sobre `chatbot_channel_mapping` y
   `chatbot_processed_messages`, o `aws dynamodb delete-item`).

## Rollback

1. **Si el sistema quedó en un estado malo y hay que destruirlo:**

   ```powershell
   terraform -chdir=infra/envs/dev destroy `
     -var "admin_token=$env:ADMIN_TOKEN_DEV" `
     -var "webhook_verify_token=$env:VERIFY_TOKEN_META" `
     -var "meta_app_secret=$env:APP_SECRET_META"
   ```

   - Verificación: `Destroy complete!`; no quedan Lambdas ni API Gateway con prefijo
     `chatbot-aws-dev`. (Las tablas DynamoDB se conservan salvo que se indique lo
     contrario; revisar `prevent_destroy` en `infra/modules/dynamodb`.)
2. **Si solo hay que retirar el webhook de Meta** (mantener la infraestructura):
   desactivar la suscripción en la app de Meta; el sistema sigue desplegado pero no
   recibe tráfico.
3. **Si un canal quedó mal registrado:** borrar la fila de `chatbot_channel_mapping`
   (paso 8) y volver a dar de alta con el paso 4.

## Contacto y escalado

- Ejecuta: quien tenga credenciales AWS de la cuenta del backend (rol DevOps/Backend).
- Aprueba: quien revisó el PR del cambio desplegado.
- Escala a: responsable técnico del Paso 9 (conversación gateway) o, si es un incidente
  de seguridad (firma rota, secreto filtrado), al rol de seguridad siguiendo
  [../security/THREAT_MODEL.md](../security/THREAT_MODEL.md).

## Registro

Tras ejecutarlo, dejar escrito (en el PR o en el ticket de despliegue): fecha/hora
(UTC), cuenta y región, resultado del `apply` (3 Lambdas correctas), el
`correlation_id` de los tres mensajes de prueba (uno por canal), y cualquier
desviación (p. ej. "el verify token de Meta no coincidía y se repitió el paso 6").
Este registro alimenta el criterio de hecho del Paso 9 (tráfico real) y la revisión
de los Pasos 13–14 (observabilidad, costos).
