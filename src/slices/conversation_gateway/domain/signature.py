"""Verificación de la firma HMAC de Meta (`X-Hub-Signature-256`): regla pura.

El ADR 0006 exige verificar la firma **siempre** (el legacy la dejó comentada en
`whatsapp_webhook_service/app.py:65-68`): aquí no existe ningún interruptor para
deshabilitarla. La comparación es en tiempo constante (`hmac.compare_digest`) para
que un atacante no pueda adivinar el secreto por tiempos de respuesta.
"""

import hashlib
import hmac


def is_valid_signature(*, payload: bytes, signature: str | None, app_secret: str) -> bool:
    """Comprueba la firma HMAC-SHA256 que Meta adjunta al cuerpo del webhook.

    Args:
        payload: Cuerpo crudo del POST (los bytes exactos que firmó Meta).
        signature: Cabecera `X-Hub-Signature-256` con formato `sha256=<hex>`;
            `None` si la cabecera no venía.
        app_secret: Secreto de la app Meta (SSM; jamás en el repositorio).

    Returns:
        `True` solo si la firma coincide en tiempo constante. Sin cabecera, sin
        prefijo `sha256=` o sin secreto configurado → `False` (se rechaza todo lo
        que no esté explícitamente firmado).

    Raises:
        (nunca): cualquier entrada inválida se traduce en `False`; el handler la
            convierte en `InvalidSignatureError`.

    Example:
        >>> import hashlib
        >>> import hmac
        >>> secreto = "app-secreta"
        >>> cuerpo = b'{"object":"whatsapp_business_account"}'
        >>> firma = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
        >>> is_valid_signature(payload=cuerpo, signature=firma, app_secret=secreto)
        True
        >>> is_valid_signature(payload=cuerpo, signature=firma, app_secret="otro")
        False
    """
    if not app_secret or not signature:
        return False
    if not signature.startswith("sha256="):
        return False
    esperada = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={esperada}", signature)
