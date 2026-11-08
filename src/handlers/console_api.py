"""API local de la consola: chat simulado, perfiles y prompts editables (Fase A).

Se ejecuta en el proceso del desarrollador, escucha solo en `127.0.0.1` por defecto y
no usa Cognito ni API Gateway. Es el composition root que puede importar varios slices
(ADR 0014) y el único lugar que conoce FastAPI. En la Fase D este mismo contrato se
desplegará detrás de API Gateway con autenticación real.
"""

import os
from typing import Annotated

from fastapi import FastAPI, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from handlers.console_runtime import ChatOutcome, ConsoleRuntime, build_default_service
from shared.contracts import AgentName
from shared.errors import AppError
from slices.tenant_prompts.application.models import PromptInfo, PromptView
from slices.tenant_prompts.application.service import TenantConfigService
from slices.tenant_prompts.domain.entities import PromptKind, TenantProfile, TenantProfileUpdate


class TenantResponse(BaseModel):
    """Perfil del comercio sin el contenido de los prompts (esos van por su endpoint)."""

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    tenant_id: str
    display_name: str
    tone: str
    language: str
    allowed_bots: list[AgentName]
    model_id: str | None = None

    @classmethod
    def from_profile(cls, profile: TenantProfile) -> "TenantResponse":
        """Convierte el modelo de dominio en la vista de la API.

        Args:
            profile: Perfil guardado.

        Returns:
            La vista con los bots ordenados para una UI estable.
        """
        return cls(
            tenant_id=profile.tenant_id,
            display_name=profile.display_name,
            tone=profile.tone,
            language=profile.language,
            allowed_bots=sorted(profile.allowed_bots),
            model_id=profile.model_id,
        )


class PromptUpdateRequest(BaseModel):
    """Cuerpo de `PUT /api/tenants/{tenant_id}/prompts/{kind}`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str = Field(min_length=1, max_length=50_000)


class ChatRequest(BaseModel):
    """Cuerpo de `POST /api/chat` (mensaje simulado de un cliente)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4096)
    customer_id: str = Field(default="57300111111", min_length=1, max_length=64)


class ChatResponse(ChatOutcome):
    """Resultado del turno más el modo de LLM efectivo de la consola."""

    llm_mode: str
    llm_warning: str


class ResetRequest(BaseModel):
    """Cuerpo de `POST /api/chat/reset`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)


class StateResponse(BaseModel):
    """Contadores de negocio del comercio, útiles para depurar la consola."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citas: int = Field(ge=0)
    pedidos: int = Field(ge=0)


def create_app(
    *,
    service: TenantConfigService | None = None,
    runtime: ConsoleRuntime | None = None,
) -> FastAPI:
    """Construye la aplicación FastAPI con sus dependencias ya compuestas.

    Args:
        service: Casos de uso de perfiles/prompts; `None` usa el JSON local.
        runtime: Runtime de grafos/sesiones; `None` se compone con `service`.

    Returns:
        Aplicación lista para `uvicorn` o `TestClient`.
    """
    servicio = service or (runtime.service if runtime is not None else build_default_service())
    runtime_final = runtime or ConsoleRuntime(service=servicio)
    app = FastAPI(
        title="ChatBotAws Console",
        version="0.1.0",
        description="Consola local de operación (Fase A): chat, perfiles y prompts.",
    )
    app.state.service = servicio
    app.state.runtime = runtime_final

    _configurar_cors(app)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        """Traduce un error tipado a JSON estable, sin stack traces ni secretos."""
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.code, "message": exc.message},
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Estado de la consola y modo de LLM efectivo."""
        return {
            "status": "ok",
            "environment": "local",
            "llm_mode": runtime_final.llm_mode,
            "llm_warning": runtime_final.llm_warning,
        }

    @app.get("/api/tenants", response_model=list[TenantResponse])
    def list_tenants() -> list[TenantResponse]:
        """Lista los comercios configurados en la consola."""
        return [TenantResponse.from_profile(p) for p in servicio.list_tenants()]

    @app.get("/api/tenants/{tenant_id}", response_model=TenantResponse)
    def get_tenant(tenant_id: Annotated[str, Path(min_length=1, max_length=64)]) -> TenantResponse:
        """Devuelve el perfil de un comercio."""
        return TenantResponse.from_profile(servicio.get_tenant(tenant_id))

    @app.put("/api/tenants/{tenant_id}", response_model=TenantResponse)
    def update_tenant(
        tenant_id: Annotated[str, Path(min_length=1, max_length=64)],
        update: TenantProfileUpdate,
    ) -> TenantResponse:
        """Actualiza los campos enviados del perfil y devuelve el resultado."""
        return TenantResponse.from_profile(servicio.update_tenant(tenant_id, update))

    @app.get("/api/tenants/{tenant_id}/prompts", response_model=list[PromptInfo])
    def list_prompts(
        tenant_id: Annotated[str, Path(min_length=1, max_length=64)],
    ) -> list[PromptInfo]:
        """Lista los prompts editables con su origen y longitud."""
        return servicio.list_prompts(tenant_id)

    @app.get("/api/tenants/{tenant_id}/prompts/{kind}", response_model=PromptView)
    def get_prompt(
        tenant_id: Annotated[str, Path(min_length=1, max_length=64)],
        kind: PromptKind,
    ) -> PromptView:
        """Devuelve el contenido efectivo de un prompt y su plantilla base."""
        return servicio.get_prompt(tenant_id, kind)

    @app.put("/api/tenants/{tenant_id}/prompts/{kind}", response_model=PromptView)
    def update_prompt(
        tenant_id: Annotated[str, Path(min_length=1, max_length=64)],
        kind: PromptKind,
        request: PromptUpdateRequest,
    ) -> PromptView:
        """Guarda un override de prompt para el comercio."""
        return servicio.update_prompt(tenant_id, kind, request.content)

    @app.delete("/api/tenants/{tenant_id}/prompts/{kind}", response_model=PromptView)
    def reset_prompt(
        tenant_id: Annotated[str, Path(min_length=1, max_length=64)],
        kind: PromptKind,
    ) -> PromptView:
        """Elimina el override y devuelve la plantilla base."""
        return servicio.reset_prompt(tenant_id, kind)

    @app.get("/api/tenants/{tenant_id}/state", response_model=StateResponse)
    def tenant_state(
        tenant_id: Annotated[str, Path(min_length=1, max_length=64)],
    ) -> StateResponse:
        """Cuenta citas y pedidos en memoria del comercio (sin exponer datos personales)."""
        return StateResponse(
            citas=len(runtime_final.citas(tenant_id)),
            pedidos=len(runtime_final.pedidos(tenant_id)),
        )

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        """Ejecuta un turno simulado y devuelve la respuesta con su traza."""
        outcome = runtime_final.chat(
            tenant_id=request.tenant_id,
            session_id=request.session_id,
            message=request.message,
            customer_id=request.customer_id,
        )
        return ChatResponse(
            **outcome.model_dump(),
            llm_mode=runtime_final.llm_mode,
            llm_warning=runtime_final.llm_warning,
        )

    @app.post("/api/chat/reset")
    def reset_chat(request: ResetRequest) -> dict[str, bool]:
        """Borra el historial y el checkpoint de una sesión."""
        runtime_final.reset(tenant_id=request.tenant_id, session_id=request.session_id)
        return {"ok": True}

    return app


def _configurar_cors(app: FastAPI) -> None:
    """Permite el origen del servidor de desarrollo de Astro/Vite.

    Args:
        app: Aplicación a la que se añade el middleware.
    """
    origenes = os.getenv(
        "CHATBOT_CONSOLE_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origen.strip() for origen in origenes.split(",") if origen.strip()],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


app = create_app()
