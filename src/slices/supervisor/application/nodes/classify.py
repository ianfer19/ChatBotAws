"""Nodo `classify`: convierte el turno en intención + confianza (decisión del LLM).

Tres degradaciones, ninguna corta el turno: salida que no es JSON → reintento único y,
si insiste, decisión ambigua (confianza 0, ruta segura); fallo del proveedor →
clasificación por palabras clave con log; JSON válido con confianza baja → lo decide
`decide` con el umbral del dominio. El prompt siempre lleva contexto e historial
(requisito 7.2): sin ellos, el propio nodo falla antes de invocar.
"""

import json

from pydantic import ValidationError as SchemaValidationError

from shared.errors import ToolError
from shared.logging import get_logger
from shared.ports import LLMMessage
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.prompts import (
    TAREA_CLASIFICAR,
    contexto_para_prompt,
    load_system_prompt,
)
from slices.supervisor.application.schemas import SupervisorDecision
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.errors import MissingTurnInputsError
from slices.supervisor.domain.routing import intent_from_keywords

_logger = get_logger(__name__)

_REINTENTO = (
    "Eso no es JSON válido. Responde SOLO con el objeto JSON de la tarea: "
    '{"intent": "...", "confidence": 0.0}'
)


def _probar_decision(texto: str) -> SupervisorDecision:
    """Extrae el primer objeto JSON del texto y lo valida contra el esquema.

    Args:
        texto: Salida cruda del modelo (puede llevar charla alrededor del JSON).

    Returns:
        La decisión validada y congelada.

    Raises:
        ValueError: Si no hay un objeto JSON en el texto.
        SchemaValidationError: Si el JSON no cumple el esquema (claves de más,
            confidence fuera de 0..1 o intent fuera del contrato).
    """
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ValueError("la respuesta no contiene un objeto JSON")
    datos = json.loads(texto[inicio : fin + 1])
    if not isinstance(datos, dict):
        raise ValueError("el JSON encontrado no es un objeto")
    return SupervisorDecision.model_validate(datos)


def _decision_por_palabras(texto: str, *, tenant_id: str) -> SupervisorDecision:
    """Clasificación de emergencia cuando Bedrock no responde (fila «Fallo de LLMPort»).

    Args:
        texto: Mensaje original del cliente.
        tenant_id: Comercio, para el log estructurado.

    Returns:
        Decisión determinista por palabras clave (confianza 1.0 por ser código, no LLM).
    """
    _logger.warning("supervisor.keyword_fallback", extra={"tenant_id": tenant_id})
    return SupervisorDecision(intent=intent_from_keywords(texto), confidence=1.0)


def _reintentar(
    deps: Deps,
    system: str,
    mensajes: list[LLMMessage],
    salida_previa: str,
    texto_original: str,
    *,
    tenant_id: str,
) -> SupervisorDecision:
    """Pide el JSON una segunda vez; si vuelve a fallar, decisión ambigua (confianza 0).

    Args:
        deps: LLM inyectado.
        system: Prompt base más la tarea de clasificación.
        mensajes: Turno completo (historial + mensaje actual).
        salida_previa: Primera salida inválida, devuelta como eco al modelo.
        texto_original: Mensaje del cliente (para el fallback por palabras clave).
        tenant_id: Comercio, para el log estructurado.

    Returns:
        La decisión del reintento, o `confidence=0.0` si la salida sigue siendo ilegible.
    """
    correccion = [
        *mensajes,
        LLMMessage(role="assistant", content=salida_previa[:1000] or "(sin texto)"),
        LLMMessage(role="user", content=_REINTENTO),
    ]
    try:
        segundo = deps.llm.invoke(messages=correccion, system=system).text
    except ToolError:
        return _decision_por_palabras(texto_original, tenant_id=tenant_id)
    try:
        return _probar_decision(segundo)
    except (ValueError, SchemaValidationError):
        return SupervisorDecision(intent="faq", confidence=0.0)


def classify(state: SupervisorState, *, deps: Deps) -> SupervisorState:
    """Clasifica el mensaje y escribe `intent` y `confidence` en el estado.

    Args:
        state: Turno con `message`, `history` y `context` (garantiza `load_context`).
        deps: LLM y lector de contexto inyectados.

    Returns:
        Estado con `intent` y `confidence` siempre presentes. Un fallo del proveedor
        degrada a palabras clave y una salida ilegible a `confidence=0.0` (ruta segura).

    Raises:
        MissingTurnInputsError: Si el turno llega sin contexto o sin historial: el
            prompt jamás se construye incompleto (requisito 7.2).
    """
    mensaje = state["message"]
    if "context" not in state or "history" not in state:
        raise MissingTurnInputsError(
            "el clasificador exige contexto e historial del turno",
            details={"correlation_id": mensaje.correlation_id},
        )
    system = (
        f"{load_system_prompt()}\n\n{TAREA_CLASIFICAR}\n\n"
        f"{contexto_para_prompt(state['context'])}"
    )
    mensajes = [*state["history"], LLMMessage(role="user", content=mensaje.text or "")]
    texto_original = mensaje.text or ""
    try:
        salida = deps.llm.invoke(messages=mensajes, system=system).text
    except ToolError:
        decision = _decision_por_palabras(texto_original, tenant_id=mensaje.tenant_id)
    else:
        try:
            decision = _probar_decision(salida)
        except (ValueError, SchemaValidationError):
            decision = _reintentar(
                deps,
                system,
                mensajes,
                salida,
                texto_original,
                tenant_id=mensaje.tenant_id,
            )
    return {**state, "intent": decision.intent, "confidence": decision.confidence}
