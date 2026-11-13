import json
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.bot.schemas import extract_messages
from app.bot.security import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


@router.get("/webhook", response_class=PlainTextResponse)
def verify_webhook(
    request: Request,
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> str:
    """Handshake que hace Meta una sola vez, al registrar la URL del webhook."""
    expected = request.app.state.settings.WEBHOOK_VERIFY_TOKEN
    if hub_mode == "subscribe" and expected and secrets.compare_digest(hub_verify_token or "", expected):
        logger.info("Webhook verificado por Meta")
        return hub_challenge or ""
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@router.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks) -> dict:
    """Recibe eventos de Meta. Responde 200 de inmediato y procesa los mensajes en segundo plano,
    para que Meta no reintente (y duplique respuestas) cuando el OCR o la visión tardan."""
    settings = request.app.state.settings
    raw = await request.body()

    if settings.WHATSAPP_APP_SECRET:
        if not verify_signature(raw, request.headers.get("X-Hub-Signature-256"), settings.WHATSAPP_APP_SECRET):
            raise HTTPException(status_code=401, detail="Firma inválida")
    elif not settings.DEBUG:
        logger.error("WHATSAPP_APP_SECRET no está configurado: se rechazan los webhooks fuera de DEBUG")
        raise HTTPException(status_code=503, detail="Webhook no configurado")

    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido") from None

    if settings.DEBUG:
        logger.debug("Webhook recibido: %s", payload)

    bot = request.app.state.bot
    for message in extract_messages(payload, settings.WHATSAPP_PHONE_NUMBER_ID or None):
        background.add_task(bot.handle_safely, message)
    return {"status": "ok"}
