"""Contexto del turno en curso (tenant/correlación) con `contextvars`.

Regla (MULTI_TENANCY §3): el handler fija el contexto al entrar y lo limpia al salir
(`bind_context` o `set_context`/`reset_context`) para que no se filtre entre invocaciones
de Lambda. Los consumidores de SQS lo rehidratan al inicio con el `tenant_id` explícito
del mensaje: el `contextvar` no viaja solo por la cola.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.types import Channel
from shared.errors.base import ContextNotSetError


class TenantContext(BaseModel):
    """Identidad del turno en curso: quién habla, con qué comercio y bajo qué correlación."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=64)
    channel: Channel
    customer_id: str = Field(min_length=1, max_length=64)


_current: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def set_context(context: TenantContext) -> Token[TenantContext | None]:
    """Fija el contexto del turno y devuelve el token para poder resetearlo.

    Args:
        context: Contexto resuelto por el gateway (o rehidratado desde SQS).

    Returns:
        Token que debe pasarse a `reset_context` al terminar la invocación.
    """
    return _current.set(context)


def reset_context(token: Token[TenantContext | None]) -> None:
    """Restaura el contexto anterior usando el token devuelto por `set_context`.

    Args:
        token: Token devuelto por `set_context` en esta misma invocación.

    Raises:
        ValueError: El token no pertenece al contexto actual (reset fuera de orden).
    """
    _current.reset(token)


def current_context() -> TenantContext | None:
    """Contexto activo, o `None` si aún no se ha fijado.

    Pensado para el logger, que debe funcionar antes de resolver el tenant (frío).
    """
    return _current.get()


def get_context() -> TenantContext:
    """Contexto activo para la lógica de negocio, que siempre lo exige.

    Returns:
        El `TenantContext` fijado por el handler.

    Raises:
        ContextNotSetError: Si el handler no fijó el contexto (bug de composición).
    """
    context = _current.get()
    if context is None:
        raise ContextNotSetError("contexto de tenant no fijado en esta invocación")
    return context


@contextmanager
def bind_context(context: TenantContext) -> Iterator[TenantContext]:
    """Helper de composición (DI): fija el contexto durante el bloque y lo limpia al salir.

    Es la forma recomendada en handlers y tests: no deja estado entre invocaciones.

    Args:
        context: Contexto del turno.

    Yields:
        El mismo contexto, por comodidad del llamador.
    """
    token = set_context(context)
    try:
        yield context
    finally:
        reset_context(token)
