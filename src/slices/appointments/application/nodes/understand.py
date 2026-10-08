"""Nodo `understand`: interpreta el turno con el LLM y lo vuelve estructura validada.

Si el modelo no responde JSON válido (texto libre, JSON con claves de más), se reintenta
una vez y, si insiste, el turno degrada a una propuesta de aclaración — nunca a una
tool: un fallo de formato no puede acabar en una acción sobre datos.
"""

import json

from pydantic import ValidationError as SchemaValidationError

from shared.ports import LLMMessage
from slices.appointments.application.deps import Deps
from slices.appointments.application.prompts import TAREA_INTERPRETAR, load_system_prompt
from slices.appointments.application.schemas import AppointmentProposal
from slices.appointments.application.state import AgentState

_RESPUESTA_FALLBACK = (
    "No entendí tu mensaje. ¿Puedes repetirlo indicando la fecha, la hora, "
    "tu nombre y un contacto?"
)


def _probar_propuesta(texto: str) -> AppointmentProposal:
    """Extrae el primer objeto JSON del texto y lo valida contra el esquema.

    Args:
        texto: Salida cruda del modelo (puede llevar charla alrededor del JSON).

    Returns:
        La propuesta validada y congelada.

    Raises:
        ValueError: Si no hay un objeto JSON en el texto.
        SchemaValidationError: Si el JSON no cumple el esquema (p. ej. claves de más).
    """
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ValueError("la respuesta no contiene un objeto JSON")
    datos = json.loads(texto[inicio : fin + 1])
    if not isinstance(datos, dict):
        raise ValueError("el JSON encontrado no es un objeto")
    return AppointmentProposal.model_validate(datos)


def _interpretar_con_reintento(
    deps: Deps, system: str, mensajes: list[LLMMessage], texto: str
) -> AppointmentProposal:
    """Pide el JSON una segunda vez tras una salida inválida; si vuelve a fallar, aclaración.

    Args:
        deps: LLM inyectado.
        system: Prompt base más la tarea de interpretación.
        mensajes: Historial del turno con el mensaje del cliente.
        texto: Salida inválida de la primera llamada (se le pasa como eco al modelo).

    Returns:
        La propuesta del reintento o una propuesta `action="reply"` de aclaración.
    """
    correccion = [
        *mensajes,
        LLMMessage(role="assistant", content=texto[:1000] or "(sin texto)"),
        LLMMessage(
            role="user",
            content="Eso no es JSON válido. Responde SOLO con el objeto JSON de la tarea.",
        ),
    ]
    segundo = deps.llm.invoke(messages=correccion, system=system).text
    try:
        return _probar_propuesta(segundo)
    except (ValueError, SchemaValidationError):
        return AppointmentProposal(action="reply", reply=_RESPUESTA_FALLBACK)


def understand(state: AgentState, *, deps: Deps) -> AgentState:
    """Interpreta el mensaje actual y escribe `proposal` en el estado.

    Args:
        state: Estado del turno; usa `user_message` y `history` (ya recortado).
        deps: LLM inyectado por el constructor del grafo.

    Returns:
        Estado con `proposal` siempre presente; un fallo de formato degrada a
        `action="reply"` en lugar de romper el turno.

    Raises:
        ToolError: Si el propio LLM falla (red, 5xx); lo traduce el adapter y el
            turno se interrumpe fuera de este nodo.
    """
    system = f"{load_system_prompt()}\n\n{TAREA_INTERPRETAR}"
    mensajes = [
        *list(state.get("history") or []),
        LLMMessage(role="user", content=state["user_message"]),
    ]
    texto = deps.llm.invoke(messages=mensajes, system=system).text
    try:
        proposal = _probar_propuesta(texto)
    except (ValueError, SchemaValidationError):
        proposal = _interpretar_con_reintento(deps, system, mensajes, texto)
    return {**state, "proposal": proposal}
