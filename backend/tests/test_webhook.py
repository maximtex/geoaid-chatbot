import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def sign(body: bytes, secret: str = "app-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def text_payload(body: str = "Hola", wamid: str = "wamid.1", phone_id: str = "PHONE_ID") -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15550000000", "phone_number_id": phone_id},
                            "contacts": [{"profile": {"name": "Ana"}, "wa_id": "573001234567"}],
                            "messages": [
                                {"from": "573001234567", "id": wamid, "timestamp": "1731360000", "type": "text", "text": {"body": body}}
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode()


@pytest.fixture
def api(settings, client, session_factory):
    with TestClient(create_app(settings, client, session_factory)) as test_client:
        yield test_client


def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}


def test_handshake_correcto_devuelve_el_challenge(api):
    response = api.get(
        "/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1158201444"},
    )
    assert response.status_code == 200
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


def test_handshake_con_token_incorrecto_es_403(api):
    response = api.get(
        "/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "otro", "hub.challenge": "x"},
    )
    assert response.status_code == 403


def test_post_sin_firma_es_401(api, client):
    response = api.post("/api/v1/whatsapp/webhook", content=text_payload())
    assert response.status_code == 401
    assert client.sent == []


def test_post_con_firma_falsa_es_401(api):
    body = text_payload()
    response = api.post("/api/v1/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sign(body, "otra")})
    assert response.status_code == 401


def test_post_firmado_procesa_el_mensaje(api, client):
    body = text_payload()
    response = api.post("/api/v1/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    # TestClient ejecuta las tareas en segundo plano antes de devolver la respuesta.
    assert client.read == ["wamid.1"]
    assert any(to == "573001234567" for to, _ in client.sent)


def test_post_de_otro_numero_se_ignora(api, client):
    body = text_payload(phone_id="OTRO_NUMERO")
    response = api.post("/api/v1/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 200
    assert client.sent == []


def test_post_solo_con_statuses_no_responde(api, client):
    body = json.dumps(
        {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.x", "status": "delivered"}]}}]}]}
    ).encode()
    response = api.post("/api/v1/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 200
    assert client.sent == []


def test_json_invalido_es_400(api):
    body = b"no es json"
    response = api.post("/api/v1/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert response.status_code == 400


def test_sin_app_secret_fuera_de_debug_rechaza(settings, client, session_factory):
    insecure = settings.model_copy(update={"WHATSAPP_APP_SECRET": "", "DEBUG": False})
    with TestClient(create_app(insecure, client, session_factory)) as api:
        assert api.post("/api/v1/whatsapp/webhook", content=text_payload()).status_code == 503


def test_sin_app_secret_en_debug_acepta(settings, client, session_factory):
    debug = settings.model_copy(update={"WHATSAPP_APP_SECRET": "", "DEBUG": True})
    with TestClient(create_app(debug, client, session_factory)) as api:
        assert api.post("/api/v1/whatsapp/webhook", content=text_payload()).status_code == 200
