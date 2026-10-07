"""Configuración cargada de variables de entorno con Pydantic Settings; nunca secretos en código."""

from shared.config.settings import Settings, load_settings

__all__ = ["Settings", "load_settings"]
