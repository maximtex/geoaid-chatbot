import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import Chat
from tests.test_flow import complete_report

PERSONAL_FIELDS = {"citizen_name", "citizen_document_id", "user_phone", "address_text", "confirmation_code", "phone"}


@pytest.fixture
def api(settings, client, session_factory):
    with TestClient(create_app(settings, client, session_factory)) as test_client:
        yield test_client


async def test_publico_anonimizado_y_sin_borradores(bot, client, session_factory, api):
    sent = Chat(bot, client, phone="573001110000")
    await complete_report(sent)
    draft = Chat(bot, client, phone="573002220000")
    await draft.text("hola")
    await draft.text("acepto")  # crea un borrador que no debe aparecer

    data = api.get("/api/v1/reports/public").json()
    assert len(data) == 1
    [report] = data
    assert not PERSONAL_FIELDS & report.keys()
    assert report["lat"] == 4.711 and report["lon"] == -74.072  # redondeado a 3 decimales
    assert report["municipality"] == "Armenia, Quindío"
    assert report["damage_level"] == "AMARILLO"
    assert report["has_vulnerable"] is True
    body = api.get("/api/v1/reports/public").text
    assert "1015234890" not in body and "573001110000" not in body and "Calle 10" not in body


async def test_coordenadas_redondeadas_todo_escrito(bot, client, api):
    """Recorrido completo respondiendo solo con texto (sin tocar botones ni listas)."""
    chat = Chat(bot, client, phone="573003330000")
    for answer in ("hola", "acepto", "vivienda", "si"):
        await chat.text(answer)
    await chat.location(2.4448123, -76.6147456)
    for answer in (
        "urbana", "Calle 5 # 1-1", "Popayán",
        "5",  # habitabilidad: no, a la intemperie
        "si",  # heridos
        "ni agua ni luz", "albergue",
        "3", "2", "no", "indígena", "otro",
        "pasaporte", "Ana Pérez Ruiz", "AB12345", "no",
    ):
        await chat.text(answer)
    await chat.image("d")
    await chat.text("listo")
    [report] = api.get("/api/v1/reports/public").json()
    assert (report["lat"], report["lon"]) == (2.445, -76.615)
    assert report["has_vulnerable"] is False
    assert report["displaced"] is True and report["injured"] is True
    assert report["urgent_need"] == "ALBERGUE"
    assert report["zone"] == "URBANA"
    body =api.get("/api/v1/reports/public").text
    for secret in ("INDIGENA", "AB12345", "estrato", "ethnicity", "PASAPORTE"):
        assert secret not in body


async def test_estadisticas(bot, client, api):
    await complete_report(Chat(bot, client, phone="573004440000"))
    await complete_report(Chat(bot, client, phone="573005550000"))
    stats = api.get("/api/v1/reports/stats").json()
    assert stats["total_reports"] == 2
    assert stats["people_affected"] == 8
    assert stats["vulnerable_households"] == 2
    assert stats["displaced_households"] == 0 and stats["injured_reports"] == 0
    assert stats["by_damage_level"] == {"VERDE": 0, "AMARILLO": 2, "ROJO": 0, "SIN_CLASIFICAR": 0}
    assert stats["by_urgent_need"]["ALIMENTOS"] == 2


def test_cors_para_la_web_y_ngrok(api):
    preflight = api.options(
        "/api/v1/reports/public",
        headers={
            "Origin": "https://geo-aid-coral.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "ngrok-skip-browser-warning",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://geo-aid-coral.vercel.app"

    other = api.get("/api/v1/reports/public", headers={"Origin": "https://sitio-ajeno.com"})
    assert "access-control-allow-origin" not in other.headers
