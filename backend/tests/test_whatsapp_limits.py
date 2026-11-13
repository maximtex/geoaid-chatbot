"""Meta rechaza los mensajes interactivos que superan estos límites; aquí se detecta antes de la demo."""

import pytest

from app import content
from app.bot import state_manager as sm
from app.bot.messages import Buttons, ListMessage
from app.bot.states import State
from app.db.models import Business, Report, User


@pytest.mark.parametrize("report_type", ["VIVIENDA", "NEGOCIO"])
@pytest.mark.parametrize("zone", ["URBANA", "RURAL"])
@pytest.mark.parametrize("state", list(State))
def test_mensajes_interactivos_respetan_limites_de_meta(state, zone, report_type, bot, session_factory):
    with session_factory() as db:
        user = User(phone="573000000000", state=state, full_name="NOMBRE DE PRUEBA LARGO", document_id="1234567890")
        db.add(user)
        report = Report(user_phone=user.phone, zone=zone, report_type=report_type)
        if report_type == "NEGOCIO":
            report.business = Business(
                in_home=True,
                name="Distribuidora de Repuestos y Ferretería La Esperanza del Cauca S.A.S.",
                needs=",".join(value for value, _, _ in content.BIZ_NEED_OPTIONS),  # peor caso: las 10
            )
        db.add(report)
        db.flush()
        ctx = sm.Ctx(db=db, user=user, msg=None)  # type: ignore[arg-type]
        messages = bot._prompt(ctx, state, report)
        if state == State.WAITING_MUNICIPALITY:
            messages += [bot._municipality_page(1, report_type == "NEGOCIO"), bot._municipality_page(2)]
        for message in messages:
            if isinstance(message, Buttons):
                assert 1 <= len(message.buttons) <= 3
                assert len(message.body) <= 1024
                for button_id, title in message.buttons:
                    assert len(title) <= 20, title
                    assert len(button_id) <= 256
            if isinstance(message, ListMessage):
                assert len(message.body) <= 1024
                assert len(message.button) <= 20
                assert len(message.section_title) <= 24
                assert 1 <= len(message.rows) <= 10
                ids = [row_id for row_id, _, _ in message.rows]
                assert len(ids) == len(set(ids))
                for row_id, title, description in message.rows:
                    assert len(title) <= 24, title
                    assert len(description) <= 72, description
                    assert len(row_id) <= 200
        db.rollback()
