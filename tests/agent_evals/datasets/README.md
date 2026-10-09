# Datasets de evals

Casos de prueba versionados (JSON/YAML) que fallan si el agente regresa. Incluye los casos de regresión de la sección 7.2.

Archivos:

- `supervisor_routing.json` (Paso 4): enrutado del supervisor, con la regresión
  obligatoria `greeting_01` (el saludo jamás enruta a ventas ni invoca especialistas).
- `orders_behavior.json` (Paso 5): comportamiento del especialista de pedidos punta a
  punta por el supervisor — `order_time_01/02` (regla crítica de la hora: sin tool y
  sin invocaciones), `order_lo_de_siempre_01` (política `AUTO` con commit y ventana de
  deshacer) y `order_monto_alto_01` (monto sobre umbral → `AWAITING_CONFIRMATION`).
- `appointments_behavior.json` (Paso 5): comportamiento del especialista de citas —
  `appt_sin_hora_01` («sin hora → pide el dato», criterio del ROADMAP), 
  `appt_hora_inferida_01` (campo inferido → `CONFIRM`, no se crea nada) y
  `appt_time_01` (acción `reschedule_appointment` inexistente → degradación honesta).

Los ejecutores (`test_orders_dataset.py`, `test_appointments_dataset.py`) corren el
grafo real con un LLM doble guionizado por caso; los datos son sintéticos.
