"""El ciudadano ve el nivel de daño estimado con sus advertencias, y el revisor recibe la alerta de riesgo."""

import pytest

from app import content
from app.bot import state_manager as sm
from app.bot.state_manager import Bot
from app.db import models
from app.db.models import AlertCode
from app.services.vision_service import DamageAssessment
from tests.conftest import Chat, bodies
from tests.test_flow import alert_codes, reach_cedula, reports_of


def make_chat(settings, client, session_factory, ocr, level, raises=False) -> Chat:
    def vision(paths):
        if raises:
            raise RuntimeError("la API se cayó")
        return DamageAssessment(level=level, confidence=0.9 if level else None)

    bot = Bot(settings=settings, client=client, session_factory=session_factory, ocr=ocr, vision=vision)
    return Chat(bot, client)


async def submit_with_one_photo(chat: Chat) -> list:
    await reach_cedula(chat)  # situación: "Sí, con daños o miedo" (siguen viviendo allí)
    await chat.image(f"cedula-{chat.phone}")
    await chat.reply(sm.BTN_ID_OK)
    await chat.image("dano-1")
    return await chat.reply(sm.BTN_DONE)


@pytest.mark.parametrize(
    ("level", "expected", "warns_distance"),
    [
        (models.DamageLevel.ROJO, "Nivel de daño estimado: ALTO", True),
        (models.DamageLevel.AMARILLO, "Nivel de daño estimado: MEDIO", True),
        (models.DamageLevel.VERDE, "Nivel de daño estimado: BAJO", False),
    ],
)
async def test_ciudadano_ve_el_nivel_y_la_advertencia(settings, client, session_factory, ocr, level, expected, warns_distance):
    chat = make_chat(settings, client, session_factory, ocr, level)
    text = bodies(await submit_with_one_photo(chat))

    assert expected in text
    assert ("más de 10 metros" in text) is warns_distance
    assert "Tu reporte quedó registrado" in text
    # El nivel llega antes del código de seguimiento.
    assert text.index(expected) < text.index("Tu reporte quedó registrado")
    if level != models.DamageLevel.VERDE:
        assert content.DAMAGE_DISCLAIMER in text
    else:
        assert "no confirma" in text and "no se hace responsable" in text


async def test_sin_clasificar_da_mensaje_prudente(settings, client, session_factory, ocr):
    chat = make_chat(settings, client, session_factory, ocr, level=None)
    text = bodies(await submit_with_one_photo(chat))
    assert content.DAMAGE_UNCLASSIFIED in text
    assert "Nivel de daño estimado" not in text


async def test_si_la_vision_falla_el_reporte_sigue_y_queda_sin_clasificar(settings, client, session_factory, ocr):
    chat = make_chat(settings, client, session_factory, ocr, level=None, raises=True)
    text = bodies(await submit_with_one_photo(chat))
    assert content.DAMAGE_UNCLASSIFIED in text and "Tu reporte quedó registrado" in text
    [report] = reports_of(session_factory, chat.phone)
    assert report.damage_level is None


async def test_rojo_y_siguen_viviendo_alli_genera_alerta(settings, client, session_factory, ocr):
    chat = make_chat(settings, client, session_factory, ocr, models.DamageLevel.ROJO)
    await submit_with_one_photo(chat)
    [report] = reports_of(session_factory, chat.phone)
    assert report.damage_level == "ROJO"
    assert AlertCode.RIESGO_NO_REPORTADO in alert_codes(report)


async def test_amarillo_no_genera_alerta_de_riesgo_no_reportado(settings, client, session_factory, ocr):
    chat = make_chat(settings, client, session_factory, ocr, models.DamageLevel.AMARILLO)
    await submit_with_one_photo(chat)
    [report] = reports_of(session_factory, chat.phone)
    assert AlertCode.RIESGO_NO_REPORTADO not in alert_codes(report)


def test_damage_result_cubre_todos_los_niveles():
    for level in models.DamageLevel:
        assert content.damage_result(level.value) == content.DAMAGE_RESULT[level.value]
    assert content.damage_result(None) == content.DAMAGE_UNCLASSIFIED
    assert content.damage_result("RARO") == content.DAMAGE_UNCLASSIFIED
