import hashlib
import hmac


def verify_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Valida el encabezado X-Hub-Signature-256 que Meta agrega a cada webhook.

    Meta firma el cuerpo exacto de la petición con HMAC-SHA256 usando la clave secreta de la app.
    """
    if not signature_header or not signature_header.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))
