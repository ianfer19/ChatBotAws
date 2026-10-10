# Artefactos de Lambda

Zips de despliegue de las funciones (`conversation_gateway.zip`,
`supervisor.zip`, …). **Nunca se commitean**: este directorio solo contiene
este README y los `.zip` construidos en local o en CI.

```powershell
# Ejemplo de empaquetado (una vez exista el código de handler, Paso 9)
python -m zipapp ...    # o herramienta equivalente
# resultado: artifacts/<funcion>.zip
```

`infra/modules/lambda` lee estas rutas con `filebase64sha256` envuelto en
`try()`, así que `terraform validate` pasa sin los zips; `terraform apply`
los exige → `TODO(verify)`: estrategia de empaquetado por slice (Paso 9).
