"""REPL de desarrollo para probar el supervisor y el grafo de citas contra Bedrock.

Conversa por consola con el tenant indicado pasando por el supervisor real del Paso 4
(clasificación, saludo propio, contexto obligatorio y enrutado), que a su vez invoca el
grafo de citas con `BedrockLLM` y un repositorio en memoria. Sirve para ver un turno
completo sin desplegar nada. No es código de producción.

Uso (PowerShell, desde la raíz del repo):

    $env:AWS_PROFILE = "iastock-old"
    $env:AWS_DEFAULT_REGION = "us-east-1"
    $env:CHATBOT_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    python scripts\\chat_citas.py                     # REPL interactivo
    python scripts\\chat_citas.py --turno "hola"       # un turno y sale (smoke local)
    python scripts\\chat_citas.py --tenant Otro --debug

Comandos del REPL: `/status` (sesión y citas creadas), `/reset` (borra la ventana de
historial) y `/salir` (o Ctrl+D / Ctrl+C). No hay persistencia: la ventana de historial
vive en memoria hasta el checkpointer del Paso 8 (`TODO(decision)`).
"""

import argparse
import logging
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

# El script se ejecuta sin instalar el paquete: añade `src` al path de importación.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from botocore.exceptions import NoRegionError
from pydantic import ValidationError as PydanticValidationError

from adapters.bedrock import BedrockLLM
from shared.config import load_settings
from shared.contracts import AgentName, InboundMessage
from shared.errors import AppError
from shared.logging import configure_logging
from shared.ports import LLMMessage
from slices.appointments.application.graph import build_appointment_graph
from slices.appointments.application.schemas import OpeningHoursDay
from slices.appointments.domain.entities import Appointment
from slices.appointments.infrastructure.in_memory import InMemoryAppointmentRepository
from slices.customer_context.application.tools import CustomerContextTools
from slices.customer_context.infrastructure.in_memory import InMemoryCustomerContextStore
from slices.supervisor.application.graph import build_supervisor_graph

_TENANT_DEMO = "Sede_Elite_01"
_CLIENTE_DEMO = "57300111111"  # sintético: nunca datos reales de clientes en el repo
_HISTORIAL_MAX = 10  # ventana de mensajes que ve el LLM (mismo N que los states)
_SALIR = {"/salir", "/exit", "exit", "quit"}
# Horario de prueba (lun a vie, 9:00-18:00, hora local naive): el real llega con RAG (Paso 7).
_HORARIO: tuple[OpeningHoursDay, ...] = tuple(
    OpeningHoursDay(weekday=dia, open_time="09:00", close_time="18:00") for dia in range(5)
)
_BOTS_DEMO: frozenset[AgentName] = frozenset({"sales", "appointments", "orders", "faq"})
_AYUDA = (
    "Supervisor + grafo de citas (Paso 4) sobre Bedrock. Comandos: /status, /reset, "
    "/salir (o Ctrl+D / Ctrl+C)."
)


class _RelojLocal:
    """`ClockPort` con la hora local del ordenador, naive como el horario demo."""

    def now(self) -> datetime:
        """Toma la hora actual del sistema sin zona horaria.

        Returns:
            `datetime.now()` naive; `TODO(decision)`: tz compartida con Aurora (Paso 6).
        """
        return datetime.now()


class _Sesion:
    """Sesión de prueba: grafo del supervisor con Bedrock, historial y citas en memoria."""

    def __init__(self, *, tenant: str) -> None:
        """Carga la configuración, el modelo y compila el supervisor con su especialista.

        Args:
            tenant: Comercio simulado (el gateway lo resolverá en el Paso 9).

        Raises:
            PydanticValidationError: Si falta `CHATBOT_BEDROCK_MODEL_ID` (fail fast).
            NoRegionError: Si el entorno no define región de AWS.
            AppError: Si falta algún prompt base (citas o supervisor).
        """
        settings = load_settings()
        self.tenant = tenant
        self.modelo = settings.bedrock_model_id
        self.historial: list[LLMMessage] = []
        self.turnos = 0
        self.repo = InMemoryAppointmentRepository()
        reloj = _RelojLocal()
        llm = BedrockLLM(
            model_id=settings.bedrock_model_id,
            timeout_seconds=settings.bedrock_timeout_seconds,
        )
        citas = build_appointment_graph(
            llm=llm,
            repo=self.repo,
            clock=reloj,
            opening_hours=_HORARIO,
        )
        lector = CustomerContextTools(store=InMemoryCustomerContextStore(clock=reloj), clock=reloj)
        self.grafo = build_supervisor_graph(
            llm=llm,
            context_reader=lector,
            allowed_bots=_BOTS_DEMO,
            appointments_graph=citas,
        )

    def turno(self, mensaje: str) -> dict[str, object]:
        """Ejecuta un turno por el supervisor y recorta la ventana de historial.

        Args:
            mensaje: Texto del cliente para este turno.

        Returns:
            Estado final de LangGraph (`reply`, `routed`, `intent`, `route_error`...).
        """
        entrada = InboundMessage(
            tenant_id=self.tenant,
            correlation_id=uuid.uuid4().hex,
            channel="whatsapp",
            customer_id=_CLIENTE_DEMO,
            message_id=uuid.uuid4().hex,
            timestamp=datetime.now(),
            text=mensaje,
        )
        resultado: dict[str, object] = self.grafo.invoke(
            {"message": entrada, "history": list(self.historial)}
        )
        reply = resultado.get("reply")
        self.historial.append(LLMMessage(role="user", content=mensaje))
        if isinstance(reply, str) and reply:
            self.historial.append(LLMMessage(role="assistant", content=reply))
        del self.historial[:-_HISTORIAL_MAX]
        self.turnos += 1
        return resultado

    def citas(self) -> list[Appointment]:
        """Lista las citas del tenant en un periodo amplio (solo para depurar).

        Returns:
            Citas persistidas en memoria, ordenadas por inicio.
        """
        return list(
            self.repo.list_for_period(
                tenant_id=self.tenant,
                start=datetime(2000, 1, 1),
                end=datetime(2100, 12, 31),
            )
        )

    def reiniciar(self) -> None:
        """Vacía la ventana de historial; las citas en memoria permanecen.

        El repositorio no se recrea: el grafo recibió el actual por DI al compilar,
        así que vaciarlo obligaría a tocar `src`. `TODO(decision)`: reset completo
        cuando haya checkpointer (Paso 8).
        """
        self.historial.clear()
        self.turnos = 0


def _argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parsea la línea de comandos del script.

    Args:
        argv: Argumentos sin el nombre del programa (`None` = sys.argv).

    Returns:
        Namespace con `tenant`, `turno` y `debug`.
    """
    parser = argparse.ArgumentParser(
        description="REPL de pruebas del supervisor (y sus grafos) contra Amazon Bedrock."
    )
    parser.add_argument(
        "--tenant",
        default=_TENANT_DEMO,
        help="comercio simulado (default: %(default)s)",
    )
    parser.add_argument(
        "--turno",
        help="ejecuta un único turno con este texto y sale (smoke local)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="log DEBUG del adaptador y estado interno tras cada turno",
    )
    return parser.parse_args(argv)


def _imprimir_error(exc: AppError) -> None:
    """Vuelca un error tipado en consola sin stack trace.

    Args:
        exc: Excepción de `shared/errors` ya traducida por el sistema.
    """
    print(f"[{exc.code}] {exc.message}")
    if exc.details:
        print(f"  detalles: {exc.details}")
    causa = str(exc.__cause__) if exc.__cause__ is not None else ""
    if any(pista in causa for pista in ("credentials", "Operation not allowed", "being verified")):
        print("  pista: revisa AWS_PROFILE / AWS_DEFAULT_REGION o el acceso a modelos")


def _imprimir_turno(resultado: dict[str, object], *, debug: bool) -> None:
    """Muestra la respuesta o la ruta del turno y, si se pide, el estado interno.

    Args:
        resultado: Estado final devuelto por el grafo.
        debug: Si es `True`, imprime intención, destino y error de enrutado.
    """
    reply = resultado.get("reply")
    routed = resultado.get("routed")
    if isinstance(reply, str) and reply:
        print(f"\n{reply}\n")
    elif routed is not None:
        destino = getattr(routed, "target", "?")
        print(f"\n[enrutado a {destino}: agente especialista aún no implementado]\n")
    else:
        print("\n(sin respuesta)\n")
    if debug:
        print(
            "  [debug] "
            f"intencion={resultado.get('intent')} "
            f"confianza={resultado.get('confidence')} "
            f"destino={resultado.get('target')} "
            f"error_ruta={resultado.get('route_error')}"
        )


def _imprimir_status(sesion: _Sesion) -> None:
    """Imprime la sesión actual y las citas creadas en memoria.

    Args:
        sesion: Sesión activa del REPL.
    """
    print(f"  tenant     : {sesion.tenant}")
    print(f"  modelo     : {sesion.modelo}")
    print(f"  turnos     : {sesion.turnos}")
    print(f"  historial  : {len(sesion.historial)} mensajes (ventana {_HISTORIAL_MAX})")
    citas = sesion.citas()
    if not citas:
        print("  citas      : ninguna en memoria")
    for cita in citas:
        print(f"    {cita.id}  {cita.starts_at.isoformat()}  {cita.status}  {cita.customer_name}")


def _turno(sesion: _Sesion, mensaje: str, *, debug: bool) -> bool:
    """Ejecuta un turno e imprime su respuesta; los errores no rompen la sesión.

    Args:
        sesion: Sesión activa.
        mensaje: Texto del cliente.
        debug: Si es `True`, imprime también el estado interno.

    Returns:
        `True` si el turno terminó bien, `False` si la tool/LLM falló.
    """
    try:
        resultado = sesion.turno(mensaje)
    except AppError as exc:
        _imprimir_error(exc)
        return False
    _imprimir_turno(resultado, debug=debug)
    return True


def _repl(sesion: _Sesion, *, debug: bool) -> int:
    """Bucle interactivo: lee líneas, atiende comandos y ejecuta turnos.

    Args:
        sesion: Sesión ya construida por `main`.
        debug: Si es `True`, muestra el estado interno tras cada turno.

    Returns:
        Código de salida del proceso (0 siempre: los fallos de turno son no fatales).
    """
    print(_AYUDA)
    while True:
        try:
            linea = input("citas> ").strip()
            if not linea:
                continue
            if linea in _SALIR:
                return 0
            if linea == "/status":
                _imprimir_status(sesion)
                continue
            if linea == "/reset":
                sesion.reiniciar()
                print("historial borrado; las citas en memoria siguen (sin checkpointer)")
                continue
            _turno(sesion, linea, debug=debug)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada: configura el entorno y arranca el REPL o un turno único.

    Args:
        argv: Argumentos de línea de comandos (`None` = sys.argv).

    Returns:
        0 si todo fue bien, 2 si falta configuración (modelo/región de AWS),
        1 si la sesión no se pudo construir.
    """
    args = _argumentos(argv)
    if args.debug:
        configure_logging("DEBUG")
        # El DEBUG de botocore/urllib3 no aporta: solo se quiere la traza del sistema.
        logging.getLogger("botocore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        sesion = _Sesion(tenant=str(args.tenant))
    except PydanticValidationError:
        print("Falta el modelo: define CHATBOT_BEDROCK_MODEL_ID (ver tests/integration/README.md)")
        return 2
    except NoRegionError:
        print("Falta la región de AWS: define AWS_DEFAULT_REGION=us-east-1")
        return 2
    except AppError as exc:
        _imprimir_error(exc)
        return 1

    if args.turno:
        return 0 if _turno(sesion, str(args.turno), debug=bool(args.debug)) else 1
    return _repl(sesion, debug=bool(args.debug))


if __name__ == "__main__":
    sys.exit(main())
