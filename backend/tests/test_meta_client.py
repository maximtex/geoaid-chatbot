import json

import httpx
import pytest
import respx

from app.bot.messages import Buttons, ListMessage, LocationRequest, Text
from app.bot.meta_client import MetaAPIError, MetaClient
from app.bot.security import verify_signature

MESSAGES_URL = "https://graph.facebook.com/v21.0/PHONE_ID/messages"


@pytest.fixture
async def meta(settings):
    async with httpx.AsyncClient() as http:
        yield MetaClient(settings, http=http, backoff_seconds=0)


@respx.mock
async def test_envia_texto_con_token(meta):
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.out"}]}))
    await meta.send("573001234567", Text("Hola"))
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer token-de-prueba"
    body = json.loads(request.content)
    assert body == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "573001234567",
        "type": "text",
        "text": {"preview_url": False, "body": "Hola"},
    }


@respx.mock
async def test_payloads_interactivos(meta):
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={}))
    await meta.send("57", Buttons("¿Sí?", (("a", "Sí"), ("b", "No"))))
    await meta.send("57", ListMessage("Elige", "Ver", "Sección", (("x", "Uno", "desc"),)))
    await meta.send("57", LocationRequest("Comparte"))
    buttons, lst, location = (json.loads(c.request.content)["interactive"] for c in route.calls)
    assert buttons["action"]["buttons"][1] == {"type": "reply", "reply": {"id": "b", "title": "No"}}
    assert lst["action"]["sections"][0]["rows"][0] == {"id": "x", "title": "Uno", "description": "desc"}
    assert location == {"type": "location_request_message", "body": {"text": "Comparte"}, "action": {"name": "send_location"}}


def test_fila_sin_descripcion_y_vista_previa_de_enlaces():
    from app.bot.messages import build_payload

    lst = build_payload("57", ListMessage("b", "Ver", "S", (("x", "Uno", ""),)))
    assert lst["interactive"]["action"]["sections"][0]["rows"] == [{"id": "x", "title": "Uno"}]
    assert build_payload("57", Text("https://x", preview_url=True))["text"]["preview_url"] is True


@respx.mock
async def test_reintenta_ante_error_500(meta):
    route = respx.post(MESSAGES_URL).mock(side_effect=[httpx.Response(500), httpx.Response(200, json={})])
    await meta.send("57", Text("x"))
    assert route.call_count == 2


@respx.mock
async def test_error_400_no_se_reintenta(meta):
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(MetaAPIError):
        await meta.send("57", Text("x"))
    assert route.call_count == 1


@respx.mock
async def test_marcar_como_leido(meta):
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={}))
    await meta.mark_as_read("wamid.1")
    assert json.loads(route.calls.last.request.content) == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.1",
    }


@respx.mock
async def test_descarga_en_dos_pasos(meta):
    respx.get("https://graph.facebook.com/v21.0/MEDIA1").mock(
        return_value=httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/x", "mime_type": "image/jpeg", "file_size": 3})
    )
    binary = respx.get("https://lookaside.fbsbx.com/x").mock(return_value=httpx.Response(200, content=b"abc"))
    media = await meta.download_media("MEDIA1")
    assert (media.content, media.mime_type) == (b"abc", "image/jpeg")
    assert binary.calls.last.request.headers["Authorization"] == "Bearer token-de-prueba"


@respx.mock
async def test_descarga_rechaza_archivos_grandes(meta, settings):
    respx.get("https://graph.facebook.com/v21.0/BIG").mock(
        return_value=httpx.Response(200, json={"url": "https://x/y", "file_size": settings.MAX_MEDIA_BYTES + 1})
    )
    with pytest.raises(MetaAPIError):
        await meta.download_media("BIG")


def test_firma():
    import hashlib
    import hmac

    body = b'{"a":1}'
    good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, good, "s3cret")
    assert not verify_signature(body + b" ", good, "s3cret")
    assert not verify_signature(body, None, "s3cret")
    assert not verify_signature(body, good, "")
    assert not verify_signature(body, good.removeprefix("sha256="), "s3cret")
