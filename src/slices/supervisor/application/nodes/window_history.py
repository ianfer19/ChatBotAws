"""Nodo `window_history`: política de ventana + resumen de turnos (ROADMAP Paso 8).

Va entre `load_context` y `resolve_pending`: recorta `history` a
`deps.history_window_size` mensajes y, cuando hay desbordado, pide al LLM un
resumen de lo recortado. El resumen viaja como mensaje sintético al frente de
la ventana y se guarda en `summary` para los turnos siguientes (resumen
rodante). El proveedor caído no corta el turno: se conserva el resumen previo
(si lo había) y la ventana sigue adelante; nunca se inventa contenido.
"""

from shared.errors import ToolError
from shared.logging import get_logger
from shared.ports import LLMMessage
from slices.supervisor.application.deps import Deps
from slices.supervisor.application.prompts import TAREA_RESUMEN
from slices.supervisor.application.state import SupervisorState
from slices.supervisor.domain.errors import MissingTurnInputsError
from slices.supervisor.domain.history import (
    split_window,
    summary_message,
    without_summary,
)

_logger = get_logger(__name__)

# `TODO(verify)`: calibrar el tope de salida con los evals (Paso 14) según la
# longitud real de las conversaciones de Sahagun.
_MAX_TOKENS_RESUMEN = 400


def _entrada_del_resumen(desbordados: list[LLMMessage], previo: str | None) -> str:
    """Compone el mensaje con el resumen previo y los turnos a resumir.

    Args:
        desbordados: Turnos que salen de la ventana (orden cronológico).
        previo: Resumen de turnos anteriores, si lo había.

    Returns:
        Un único bloque de texto con roles explícitos (`user:`/`assistant:`):
        así el llamado no depende de la alternancia de roles del historial.
    """
    partes: list[str] = []
    if previo:
        partes.append(f"Resumen previo de la conversacion: {previo}")
    partes.append("Mensajes a resumir:")
    partes.extend(f"{mensaje.role}: {mensaje.content}" for mensaje in desbordados)
    return "\n".join(partes)


def _resumir(
    deps: Deps,
    desbordados: list[LLMMessage],
    previo: str | None,
    *,
    tenant_id: str,
    correlation_id: str,
) -> str | None:
    """Pide al LLM el resumen de los turnos recortados; degrada al resumen previo.

    Args:
        deps: LLM inyectado (doble en tests).
        desbordados: Turnos que salen de la ventana (orden cronológico).
        previo: Resumen de turnos anteriores, si lo había.
        tenant_id: Comercio, para el log estructurado.
        correlation_id: Turno, para el log estructurado.

    Returns:
        El resumen nuevo, o `previo` si el proveedor falló o devolvió vacío
        (nunca se inventa contenido).
    """
    mensajes = [LLMMessage(role="user", content=_entrada_del_resumen(desbordados, previo))]
    try:
        texto = deps.llm.invoke(
            messages=mensajes,
            system=TAREA_RESUMEN,
            max_tokens=_MAX_TOKENS_RESUMEN,
        ).text.strip()
    except ToolError:
        _logger.warning(
            "supervisor.summary_failed",
            extra={"tenant_id": tenant_id, "correlation_id": correlation_id},
        )
        return previo
    return texto or previo


def _componer(resumen: str | None, ventana: list[LLMMessage]) -> list[LLMMessage]:
    """Pone el resumen sintético al frente de la ventana conservada.

    Args:
        resumen: Texto del resumen, o `None` si no hay.
        ventana: Mensajes conservados (ya sin resumen).

    Returns:
        La ventana lista para `classify`: resumen primero (si existe) y luego
        los últimos mensajes en orden cronológico.
    """
    if resumen:
        return [summary_message(resumen), *ventana]
    return ventana


def window_history(state: SupervisorState, *, deps: Deps) -> SupervisorState:
    """Aplica la política de ventana y escribe `history` y `summary` en el turno.

    Args:
        state: Turno con `message` y `history` (garantiza `load_context`) y,
            opcionalmente, `summary` de turnos previos.
        deps: LLM y tamaño de ventana inyectados por el constructor del grafo.

    Returns:
        Estado con `history` recortado a la ventana (con el resumen sintético al
        frente si lo hay) y `summary` actualizado. Sin desbordado no hay llamada
        al LLM.

    Raises:
        MissingTurnInputsError: Si el turno llega sin ventana de historial.
        ValidationError: Si `deps.history_window_size` es menor que 1 (`Settings`
            ya lo valida al arrancar).
    """
    mensaje = state["message"]
    if "history" not in state:
        raise MissingTurnInputsError(
            "el turno llegó sin ventana de historial",
            details={"correlation_id": mensaje.correlation_id},
        )
    previo = state.get("summary")
    base = without_summary(state["history"])
    conservados, desbordados = split_window(base, size=deps.history_window_size)
    if not desbordados:
        return {**state, "history": _componer(previo, conservados), "summary": previo}
    resumen = _resumir(
        deps,
        desbordados,
        previo,
        tenant_id=mensaje.tenant_id,
        correlation_id=mensaje.correlation_id,
    )
    return {**state, "history": _componer(resumen, conservados), "summary": resumen}
