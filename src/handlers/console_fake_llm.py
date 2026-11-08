"""LLM simulado para la consola local: respuestas deterministas y sin AWS.

No pretende imitar a un modelo real. Sirve para que la interfaz y los grafos funcionen
sin credenciales, y para que los tests comprueben qué `system` recibió cada nodo. En
modo `auto` la consola usa Bedrock si hay credenciales; si no, cae aquí.
"""

import json
import re
from collections.abc import Sequence

from shared.ports import LLMMessage, LLMResult

_TAREA_CLASIFICAR = "TAREA: clasifica"
_TAREA_PENDIENTE = "TAREA: decide si"
_TAREA_CITAS = "TAREA: hoy es"
_TAREA_PEDIDOS = "TAREA: ahora es"
_TAREA_FAQ = "TAREA: responde la pregunta"
_TAREA_REDACTAR = "TAREA: redacta la respuesta final"
_TAREA_RESUMEN = "TAREA: resume"

_HASH_RE = re.compile(r"payload_hash:\s*([^\s]+)")


def _clasificar(texto: str) -> str:
    """Clasifica por palabras clave con el mismo vocabulario que el dominio.

    Args:
        texto: Último mensaje del cliente en minúsculas.

    Returns:
        Una de las intenciones del contrato (`greeting`, `smalltalk`, `appointments`,
        `orders`, `faq`, `sales`).
    """
    if any(palabra in texto for palabra in ("hola", "buenas", "buenos dias", "hey", "que tal")):
        return "greeting"
    if any(
        palabra in texto for palabra in ("cita", "agendar", "reservar", "turno", "disponibilidad")
    ):
        return "appointments"
    if any(
        palabra in texto
        for palabra in ("pedido", "pedir", "orden", "menu", "producto", "domicilio")
    ):
        return "orders"
    if any(
        palabra in texto
        for palabra in ("horario", "direccion", "donde", "abren", "informacion", "como")
    ):
        return "faq"
    return "faq"


class FakeLLM:
    """`LLMPort` determinista para desarrollo y tests de la consola.

    Registra el `system` de cada llamada en `systems` para que los tests puedan
    comprobar que el override de prompt del comercio llegó al nodo correcto.
    """

    def __init__(self) -> None:
        """Crea el doble con su registro de llamadas."""
        self.systems: list[str] = []

    @property
    def last_system(self) -> str | None:
        """Devuelve el último `system` recibido (o `None` si no hubo llamadas)."""
        return self.systems[-1] if self.systems else None

    def invoke(
        self,
        *,
        messages: Sequence[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Genera una respuesta determinista según la tarea del `system`.

        Args:
            messages: Historial del turno; el último mensaje es la pregunta actual.
            system: Prompt de sistema que distingue la tarea (clasificar, citas...).
            max_tokens: Ignorado por el doble.
            temperature: Ignorado por el doble.

        Returns:
            `LLMResult` con JSON válido para las tareas estructuradas o texto para las
            tareas de redacción.
        """
        del max_tokens, temperature  # el doble no muestrea
        prompt = system or ""
        self.systems.append(prompt)
        pregunta = messages[-1].content if messages else ""
        if _TAREA_CLASIFICAR in prompt:
            intencion = _clasificar(pregunta.casefold())
            return LLMResult(text=json.dumps({"intent": intencion, "confidence": 0.9}))
        if _TAREA_PENDIENTE in prompt:
            coincidencia = _HASH_RE.search(prompt)
            payload_hash = coincidencia.group(1) if coincidencia else "sin-hash"
            return LLMResult(text=json.dumps({"decision": "pass", "payload_hash": payload_hash}))
        if _TAREA_CITAS in prompt:
            return LLMResult(
                text=json.dumps(
                    {
                        "action": "reply",
                        "date": None,
                        "time": None,
                        "customer_name": None,
                        "contact": None,
                        "appointment_id": None,
                        "party_size": None,
                        "reply": (
                            "Claro, para agendar tu cita dime fecha, hora, nombre y "
                            "un medio de contacto."
                        ),
                    }
                )
            )
        if _TAREA_PEDIDOS in prompt:
            return LLMResult(
                text=json.dumps(
                    {
                        "action": "reply",
                        "query": None,
                        "category": None,
                        "order_id": None,
                        "items": [],
                        "reply": (
                            "Cuéntame qué productos quieres y la cantidad; el menú y los "
                            "precios salen del catálogo del comercio."
                        ),
                    }
                )
            )
        if _TAREA_FAQ in prompt:
            return LLMResult(
                text=f"Respuesta simulada con la evidencia recuperada para «{pregunta}»."
            )
        if _TAREA_REDACTAR in prompt:
            return LLMResult(text=f"Respuesta simulada: {pregunta}")
        if _TAREA_RESUMEN in prompt:
            return LLMResult(text="Resumen simulado de la conversación.")
        return LLMResult(text=f"Respuesta simulada: {pregunta}")
