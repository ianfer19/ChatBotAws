"""Helpers compartidos por los smoke tests reales de AWS (sin lógica de negocio).

Viven aquí las comisiones de entorno que comparten los tests de integración:
detectar credenciales locales, distinguir «cuenta sin acceso a modelos» de un fallo
real y leer el modelo configurado. En CI (sin credenciales) los tests se omiten.
"""

import os

MODELO_BEDROCK = os.environ.get("CHATBOT_BEDROCK_MODEL_ID")


def hay_credenciales() -> bool:
    """Comprueba en local si la cadena de credenciales de AWS está disponible.

    Returns:
        `True` si hay clave/secretos, `AWS_PROFILE` o un perfil por defecto en disco;
        `False` si no hay con qué firmar (caso de CI).
    """
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.getenv("AWS_PROFILE"):
        return True
    credenciales = (
        os.path.expanduser(r"~\.aws\credentials")
        if os.name == "nt"
        else os.path.expanduser("~/.aws/credentials")
    )
    return os.path.isfile(credenciales) or os.path.isfile(os.path.expanduser("~/.aws/config"))


def es_acceso_pendiente(error: Exception) -> bool:
    """Distingue «la cuenta aún no tiene acceso a modelos» de un fallo real del código.

    Args:
        error: Excepción lanzada por el adapter; la causa original es `ClientError`.

    Returns:
        `True` si Bedrock reporta verificación de cuenta u operación no permitida aún.
    """
    causa = error.__cause__
    mensaje = str(causa) if causa is not None else ""
    return "Operation not allowed" in mensaje or "being verified" in mensaje
