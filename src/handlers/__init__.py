"""Composition roots: consumer de producción y consola local (Paso 9, Fase A).

Único lugar del repo que importa **varios slices a la vez**: es el espejo productivo de
`scripts/chat_citas.py` (decisión de la Fase 6: composición en un paquete top-level
`src/handlers/`, no dentro de ningún slice, para no romper el aislamiento entre slices).
Contiene el `consumer` (SQS → supervisor → respuesta al canal) y la consola local
(FastAPI + runtime por comercio). La webhook y el admin del gateway viven en
`src/slices/conversation_gateway/handler/` (composición propia de un solo slice). Los
handlers de Lambdas de cada entorno importan `handlers.consumer.main`.
"""
