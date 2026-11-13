"""Reportes de negocios (pymes): reutilizan la ubicación, la identidad y las fotos del flujo de vivienda."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import content
from app.bot import state_manager as sm
from app.bot.messages import Buttons, ListMessage, LocationRequest
from app.bot.states import State
from app.db.models import AlertCode, Business, Report, ReportStatus
from app.main import create_app
from tests.conftest import Chat, bodies
from tests.test_flow import alert_codes, household_block, location_block, situation_block, state_of


def business_of(session_factory, phone: str) -> list[tuple[Report, Business | None]]:
    with session_factory() as db:
        reports = db.scalars(select(Report).where(Report.user_phone == phone).order_by(Report.id)).all()
        result = []
        for r in reports:
            _ = (r.alerts, r.media_files, r.business)
            result.append((r, r.business))
        return result


async def start_business(chat: Chat) -> None:
    """Saludo → términos → Mi negocio → en el negocio → ubicación urbana (queda en el nombre del negocio)."""
    await chat.text("Hola")
    await chat.reply(sm.BTN_ACCEPT)
    await chat.reply(sm.BTN_TYPE_BUSINESS)
    await chat.reply(sm.BTN_YES)
    await location_block(chat, "Popayán, Cauca")


async def business_block(
    chat: Chat,
    *,
    role: str = "DUENO",
    in_home: bool = False,
    operating: str = "CERRADO_TEMPORAL",
    damage: str = "MENOR",
    employees: str = "2_5",
    tenure: str = "ARRENDADO",
    registry: str = "RENOVADO",
    nit: str = "900.123.456-7",
    debts: str = "1",
    losses: str = "1,3,4",
    loss_value: str = "20_50M",
    needs: str = "1,6",
    top_need: str = "CREDITO",
) -> None:
    """Responde el bloque del negocio con toques, siguiendo las preguntas que aplican a cada caso."""
    await chat.text("Tienda Doña Rosa")
    await chat.reply(sm.BIZ_ROLE_PREFIX + role)
    await chat.reply(sm.BIZ_PREMISES_PREFIX + "PUNTO_VENTA_BODEGA")
    await chat.reply(sm.BTN_YES if in_home else sm.BTN_NO)
    await chat.reply(sm.BIZ_OPERATING_PREFIX + operating)
    await chat.reply(sm.BIZ_DAMAGE_PREFIX + damage)
    if operating in content.BIZ_REOPENING_ASKED_FOR:
        await chat.reply(sm.BIZ_REOPENING_PREFIX + "1_4_SEMANAS")
    await chat.reply(sm.BTN_NO)  # heridos
    await chat.reply(sm.SERVICES_PREFIX + "SOLO_LUZ")
    await chat.reply(sm.BIZ_SECTOR_PREFIX + "COMERCIO")
    await chat.reply(sm.BIZ_AGE_PREFIX + "5_10")
    await chat.reply(sm.BIZ_EMPLOYEES_PREFIX + employees)
    await chat.text("3")  # empleos en riesgo
    await chat.reply(sm.BIZ_TENURE_PREFIX + tenure)
    await chat.reply(sm.BTN_YES)  # vende por WhatsApp o redes
    if role in content.BIZ_DECISION_ROLES:
        await chat.reply(sm.BIZ_REGISTRY_PREFIX + registry)
        if registry in content.BIZ_REGISTERED:
            await chat.reply(sm.BIZ_LEGAL_FORM_PREFIX + "PERSONA_NATURAL")
            await chat.text(nit)
        await chat.reply(sm.BTN_YES)  # RUT
        await chat.reply(sm.BTN_NOT_APPLICABLE)  # facturación electrónica
        if employees != "1":
            await chat.reply(sm.BTN_NO)  # seguridad social pendiente
        await chat.reply(sm.BTN_YES)  # ICA
        if tenure == "PROPIO":
            await chat.reply(sm.BTN_UNKNOWN)  # predial
        await chat.reply(sm.BIZ_SALES_PREFIX + "5_20M")
        await chat.text(debts)
        await chat.reply(sm.BIZ_PAYMENT_PREFIX + "BILLETERA")
    await chat.text("1, 3")  # liderazgo
    await chat.text(losses)
    if losses not in ("0", "nada"):
        await chat.reply(sm.BIZ_LOSS_VALUE_PREFIX + loss_value)
    await chat.reply(sm.BTN_NO)  # seguro
    await chat.text(needs)
    if "," in needs:
        await chat.reply(sm.BIZ_TOP_NEED_PREFIX + top_need)
    if role not in content.BIZ_LEGAL_REP_ROLES:
        await chat.text("Rosa Elena Quintero")
        await chat.text("31.234.567")


async def identity_and_photos(chat: Chat) -> list:
    await chat.reply(sm.DOC_TYPE_PREFIX + "CC")
    await chat.reply(sm.BTN_ID_PHOTO)
    await chat.image(f"cedula-{chat.phone}")
    await chat.reply(sm.BTN_ID_OK)
    await chat.image(f"local-{chat.phone}")
    return await chat.reply(sm.BTN_DONE)


async def complete_business_report(chat: Chat, **kwargs) -> list:
    await start_business(chat)
    await business_block(chat, **kwargs)
    return await identity_and_photos(chat)


# ---------------------------------------------------------------- camino feliz


async def test_reporte_de_negocio_completo_como_dueno(chat, session_factory):
    await chat.text("Hola")
    replies = await chat.reply(sm.BTN_ACCEPT)
    assert "Qué quieres reportar" in replies[-1].body
    replies = await chat.reply(sm.BTN_TYPE_BUSINESS)
    assert "ubicación del negocio" in bodies(replies) and "en el negocio o local" in replies[-1].body
    replies = await chat.reply(sm.BTN_YES)
    assert isinstance(replies[-1], LocationRequest) and "dónde está el negocio" in replies[-1].body
    assert "El negocio está en *zona urbana*" in bodies(await chat.location())
    assert "dirección del negocio" in bodies(await chat.reply(sm.BTN_ZONE_URBAN))
    replies = await chat.text("Carrera 6 # 4-20, barrio Centro")
    assert isinstance(replies[-1], ListMessage) and "municipio* está el negocio" in replies[-1].body
    assert "se llama el *negocio*" in bodies(await chat.reply(sm.MUNICIPALITY_PREFIX + "POPAYAN"))

    # El rol va al principio y usa el nombre del negocio
    replies = await chat.text("Tienda Doña Rosa")
    assert isinstance(replies[-1], ListMessage) and "relación* con *Tienda Doña Rosa*" in replies[-1].body
    assert all(row[0] != sm.BTN_SKIP for row in replies[-1].rows)  # el rol es obligatorio
    replies = await chat.reply(sm.BIZ_ROLE_PREFIX + "DUENO")
    assert "tipo de *local*" in replies[-1].body
    assert "dentro de tu vivienda" in bodies(await chat.reply(sm.BIZ_PREMISES_PREFIX + "PUNTO_VENTA_BODEGA"))
    assert "seguir funcionando" in bodies(await chat.reply(sm.BTN_NO))
    assert "estructura del local" in bodies(await chat.reply(sm.BIZ_OPERATING_PREFIX + "CERRADO_TEMPORAL"))
    replies = await chat.reply(sm.BIZ_DAMAGE_PREFIX + "GRAVE")
    assert "no entres ni atiendas" in bodies(replies) and "volver a funcionar normal" in replies[-1].body
    assert "heridas" in bodies(await chat.reply(sm.BIZ_REOPENING_PREFIX + "1_3_MESES"))
    assert "agua y luz" in bodies(await chat.reply(sm.BTN_NO))
    assert "sector económico" in bodies(await chat.reply(sm.SERVICES_PREFIX + "SOLO_LUZ"))
    assert "Hace cuánto" in bodies(await chat.reply(sm.BIZ_SECTOR_PREFIX + "COMERCIO"))
    assert "trabajan" in bodies(await chat.reply(sm.BIZ_AGE_PREFIX + "5_10"))
    assert "no pueden trabajar" in bodies(await chat.reply(sm.BIZ_EMPLOYEES_PREFIX + "2_5"))
    assert "*local* del negocio" in bodies(await chat.text("3 personas"))
    assert "WhatsApp, redes" in bodies(await chat.reply(sm.BIZ_TENURE_PREFIX + "PROPIO"))

    # Obligaciones y finanzas: el dueño sí las ve, con el aviso de confianza
    replies = await chat.reply(sm.BTN_YES)
    assert "No se comparten con la DIAN" in bodies(replies) and "Registro Mercantil" in replies[-1].body
    assert "constituido" in bodies(await chat.reply(sm.BIZ_REGISTRY_PREFIX + "SIN_RENOVAR"))
    assert "NIT" in bodies(await chat.reply(sm.BIZ_LEGAL_FORM_PREFIX + "SOCIEDAD"))
    replies = await chat.text("900.123.456-7")
    assert isinstance(replies[-1], Buttons) and "RUT" in replies[-1].body
    assert [title for _, title in replies[-1].buttons] == ["Sí, al día", "No, pendiente", "No sé"]
    replies = await chat.reply(sm.BTN_YES)
    assert "facturación electrónica" in replies[-1].body and replies[-1].buttons[2][1] == "No estoy obligado"
    assert "seguridad social" in bodies(await chat.text("no"))  # facturación pendiente, escrito
    assert "ICA" in bodies(await chat.reply(sm.BTN_UNKNOWN))
    assert "predial" in bodies(await chat.reply(sm.BTN_NO))  # local propio: se pregunta el predial
    assert "vendía al mes" in bodies(await chat.reply(sm.BTN_YES))
    assert "deudas o créditos" in bodies(await chat.reply(sm.BIZ_SALES_PREFIX + "5_20M"))
    replies = await chat.text("1, 4")
    assert "apoyo en dinero" in replies[-1].body
    assert "liderado" in bodies(await chat.reply(sm.BIZ_PAYMENT_PREFIX + "AMBAS"))

    # Pérdidas y necesidades (selección múltiple + la más urgente)
    replies = await chat.text("1,3")
    assert isinstance(replies[-1], Buttons) and "Equipos tecnológicos" in replies[-1].body
    assert "vale lo que se perdió" in bodies(await chat.text("1, 3, 4"))
    assert "seguro" in bodies(await chat.reply(sm.BIZ_LOSS_VALUE_PREFIX + "50_200M"))
    replies = await chat.reply(sm.BTN_UNKNOWN)
    assert "Puedes elegir varias" in replies[-1].body and "Apoyo para pagar la nómina" in replies[-1].body
    replies = await chat.text("1, 3, 6")
    top = replies[-1]
    assert isinstance(top, ListMessage) and "más urgente" in top.body
    assert [title for _, title, _ in top.rows] == ["Crédito o refinanciación", "Apoyo para la nómina", "Reponer inventario"]
    replies = await chat.reply(sm.BIZ_TOP_NEED_PREFIX + "NOMINA")
    assert "documento de identidad" in replies[-1].body  # el dueño es el representante: no se pide aparte
    await chat.reply(sm.DOC_TYPE_PREFIX + "CC")
    await chat.reply(sm.BTN_ID_PHOTO)
    await chat.image("cedula-1")
    assert "mercancía, maquinaria" in bodies(await chat.reply(sm.BTN_ID_OK))
    await chat.image("local-1")
    replies = await chat.reply(sm.BTN_DONE)
    assert "visita a tu negocio" in bodies(replies)

    [(report, b)] = business_of(session_factory, chat.phone)
    assert report.report_type == "NEGOCIO" and report.status == ReportStatus.PENDIENTE_REVISION
    assert report.habitability is None and report.household_size is None  # preguntas solo de vivienda
    assert (b.name, b.reporter_role, b.reporter_is_legal_rep) == ("Tienda Doña Rosa", "DUENO", True)
    assert (b.premises, b.in_home, b.operating_status) == ("PUNTO_VENTA_BODEGA", False, "CERRADO_TEMPORAL")
    assert (b.structural_damage, b.reopening_estimate) == ("GRAVE", "1_3_MESES")
    assert (b.sector, b.age_range, b.employees_range, b.jobs_at_risk) == ("COMERCIO", "5_10", "2_5", 3)
    assert (b.tenure, b.digital_sales) == ("PROPIO", True)
    assert (b.registry_status, b.legal_form, b.nit) == ("SIN_RENOVAR", "SOCIEDAD", "9001234567")
    assert (b.rut_status, b.einvoice_status, b.social_security_status) == ("AL_DIA", "PENDIENTE", "NO_SABE")
    assert (b.ica_status, b.predial_status) == ("PENDIENTE", "AL_DIA")
    assert (b.monthly_sales, b.debts, b.payment_account) == ("5_20M", "BANCO,GOTA_A_GOTA", "AMBAS")
    assert b.leadership_groups == "MUJER,VICTIMA_CONFLICTO"
    assert b.losses == "MERCANCIA,MAQUINARIA,EQUIPOS_TECNOLOGICOS" and b.loss_value == "50_200M"
    assert (b.insurance, b.needs, b.urgent_need) == ("NO_SABE", "CREDITO,NOMINA,INVENTARIO", "NOMINA")
    assert (b.legal_rep_name, b.legal_rep_document) == ("ANA MARÍA PÉREZ", "1015234890")
    assert alert_codes(report) == {
        AlertCode.NEGOCIO_CERRADO,
        AlertCode.PERDIDA_ALTA,
        AlertCode.PRESTAMO_INFORMAL,
        AlertCode.OBLIGACIONES_PENDIENTES,
    }  # sin RIESGO_ESTRUCTURAL: está cerrado
    [pending] = [a.detail for a in report.alerts if a.code == AlertCode.OBLIGACIONES_PENDIENTES]
    assert pending == "No está al día con: renovación del Registro Mercantil, facturación electrónica, ICA."


async def test_negocio_respondido_todo_escrito(chat, session_factory):
    for answer in ("hola", "acepto", "negocio", "si"):
        await chat.text(answer)
    await chat.location()
    for answer in (
        "urbana", "Calle 1 # 2-3", "Cali",
        "Panadería La Espiga", "gerente o administrador", "taller o planta", "no",
        "1",  # funciona con normalidad: no se pregunta la reapertura
        "sin daños visibles", "no", "agua y luz", "restaurante o alimentos", "1", "solo yo", "ninguna",
        "arrendado", "no",
        "no sé",  # registro: sin registro claro no se pide tipo de persona ni NIT
        "si", "no estoy obligado",  # RUT y facturación; solo yo: sin seguridad social
        "al dia",  # ICA; arrendado: sin predial
        "prefiero no responder", "ninguna", "ninguna",  # ventas, deudas, cuenta
        "0", "nada", "si", "9",  # liderazgo, pérdidas, seguro, una sola necesidad
        "Pedro Pérez Gómez", "12345678",  # el gerente da los datos del representante
    ):
        await chat.text(answer)
    assert state_of(session_factory, chat) == State.WAITING_DOC_TYPE
    [(_, b)] = business_of(session_factory, chat.phone)
    assert (b.reporter_role, b.reporter_is_legal_rep) == ("GERENTE", False)
    assert (b.premises, b.operating_status, b.reopening_estimate) == ("TALLER_PLANTA", "NORMAL", None)
    assert (b.structural_damage, b.sector, b.employees_range, b.jobs_at_risk) == ("SIN_DANO", "ALIMENTOS", "1", 0)
    assert (b.registry_status, b.legal_form, b.nit) == ("NO_SABE", None, None)
    assert (b.rut_status, b.einvoice_status, b.social_security_status) == ("AL_DIA", "NO_APLICA", None)
    assert (b.ica_status, b.predial_status) == ("AL_DIA", None)
    assert (b.monthly_sales, b.debts, b.payment_account) == ("NO_RESPONDE", "NINGUNO", "NINGUNA")
    assert (b.leadership_groups, b.losses, b.loss_value) == ("NINGUNO", "NINGUNO", None)
    assert (b.needs, b.urgent_need) == ("ASESORIA", "ASESORIA")  # una sola: es la más urgente
    assert (b.legal_rep_name, b.legal_rep_document) == ("PEDRO PÉREZ GÓMEZ", "12345678")


# ---------------------------------------------------------------- reglas del flujo


async def test_empleado_no_ve_obligaciones_y_da_datos_del_representante(chat, session_factory):
    await start_business(chat)
    await business_block(chat, role="EMPLEADO", needs="4")
    assert state_of(session_factory, chat) == State.WAITING_DOC_TYPE
    await identity_and_photos(chat)
    [(report, b)] = business_of(session_factory, chat.phone)
    assert (b.reporter_role, b.reporter_is_legal_rep) == ("EMPLEADO", False)
    assert (b.legal_rep_name, b.legal_rep_document) == ("ROSA ELENA QUINTERO", "31234567")
    for field in ("registry_status", "nit", "rut_status", "social_security_status", "monthly_sales", "debts", "payment_account"):
        assert getattr(b, field) is None, field
    assert report.citizen_name == "ANA MARÍA PÉREZ"  # quien reporta, distinto del representante
    assert report.skipped_questions is None  # lo que no aplica no cuenta como saltado
    assert AlertCode.OBLIGACIONES_PENDIENTES not in alert_codes(report)
    assert "No se comparten con la DIAN" not in bodies([m for _, m in chat.client.sent])


async def test_representante_invalido_se_repite(chat, session_factory):
    await start_business(chat)
    await business_block(chat, role="CONTADOR", needs="2")  # contador: ve las obligaciones y no es el representante
    [(_, b)] = business_of(session_factory, chat.phone)
    assert b.rut_status == "AL_DIA" and b.legal_rep_name == "ROSA ELENA QUINTERO"

    await chat.text("cancelar")
    await chat.reply(sm.BTN_NEW_BUSINESS)
    await chat.reply(sm.BTN_YES)
    await location_block(chat)
    await chat.text("Taller El Tornillo")
    await chat.reply(sm.BIZ_ROLE_PREFIX + "FAMILIAR")
    await chat.reply(sm.BIZ_PREMISES_PREFIX + "TALLER_PLANTA")
    for _ in range(15):  # vivienda, funcionamiento, daño, heridos, servicios ... liderazgo, pérdidas, seguro, necesidades
        await chat.text("saltar")
    assert state_of(session_factory, chat) == State.WAITING_BIZ_REP_NAME
    assert "nombres y apellidos" in bodies(await chat.text("Rosa"))
    await chat.text("rosa elena quintero")
    assert "entre 5 y 12" in bodies(await chat.text("12-3"))
    assert state_of(session_factory, chat) == State.WAITING_BIZ_REP_DOCUMENT


async def test_solo_yo_no_pregunta_seguridad_social_y_arrendado_no_pregunta_predial(chat, session_factory):
    await start_business(chat)
    await business_block(chat, employees="1", tenure="ARRENDADO", needs="1")
    [(_, b)] = business_of(session_factory, chat.phone)
    assert b.social_security_status is None and b.predial_status is None
    assert b.ica_status == "AL_DIA" and b.rut_status == "AL_DIA"
    assert state_of(session_factory, chat) == State.WAITING_DOC_TYPE


async def test_negocio_informal_no_pide_nit_ni_tipo_de_persona(chat, session_factory):
    await start_business(chat)
    await business_block(chat, registry="NO", needs="1")
    sent = bodies([m for _, m in chat.client.sent])
    assert "se registra igual" in sent and "constituido" not in sent
    [(report, b)] = business_of(session_factory, chat.phone)
    assert (b.registry_status, b.legal_form, b.nit) == ("NO", None, None)
    assert AlertCode.NEGOCIO_INFORMAL in alert_codes(report)


async def test_dano_grave_con_el_negocio_abierto_alerta_riesgo_estructural(chat, session_factory):
    await start_business(chat)
    await chat.text("Droguería San José")
    await chat.reply(sm.BIZ_ROLE_PREFIX + "SOCIO")
    await chat.reply(sm.BIZ_PREMISES_PREFIX + "PUNTO_VENTA")
    await chat.reply(sm.BTN_NO)
    await chat.reply(sm.BIZ_OPERATING_PREFIX + "NORMAL")
    replies = await chat.reply(sm.BIZ_DAMAGE_PREFIX + "COLAPSO")
    assert "no entres ni atiendas" in bodies(replies)
    assert "heridas" in replies[-1].body  # funciona normal: no se pregunta la reapertura
    [(report, _)] = business_of(session_factory, chat.phone)
    assert AlertCode.RIESGO_ESTRUCTURAL in alert_codes(report)


async def test_saltar_preguntas_del_negocio(chat, session_factory):
    await start_business(chat)
    assert "necesario" in bodies(await chat.text("saltar"))
    assert state_of(session_factory, chat) == State.WAITING_BIZ_NAME
    await chat.text("Ferretería Central")
    assert "No entendí" in bodies(await chat.text("saltar"))  # rol obligatorio
    await chat.reply(sm.BIZ_ROLE_PREFIX + "REP_LEGAL")
    assert "No entendí" in bodies(await chat.text("saltar"))  # tipo de local obligatorio
    await chat.reply(sm.BIZ_PREMISES_PREFIX + "BODEGA")
    for _ in range(4):  # en vivienda, funcionamiento, daño, heridos
        await chat.reply(sm.BTN_SKIP)
    for _ in range(19):  # servicios ... necesidades (reapertura, tipo de persona, NIT, predial, valor y la más urgente no aplican)
        await chat.text("saltar")
    assert state_of(session_factory, chat) == State.WAITING_DOC_TYPE

    [(report, b)] = business_of(session_factory, chat.phone)
    assert report.skipped_questions == (
        "negocio_en_vivienda,funcionamiento,dano_local,heridos,servicios,sector,antiguedad,trabajadores,"
        "empleos_en_riesgo,tenencia_local,ventas_digitales,registro_mercantil,rut,facturacion_electronica,"
        "seguridad_social,ica,ventas_mensuales,deudas,cuenta_apoyos,liderazgo,perdidas,seguro,necesidades_negocio"
    )
    assert b.name == "Ferretería Central" and b.reporter_is_legal_rep is True and b.needs is None


async def test_entradas_invalidas_en_negocio(chat, session_factory):
    await start_business(chat)
    await chat.text("Taller El Tornillo")
    await chat.reply(sm.BIZ_ROLE_PREFIX + "DUENO")
    await chat.reply(sm.BIZ_PREMISES_PREFIX + "TALLER_PLANTA")
    await chat.reply(sm.BTN_NO)
    await chat.reply(sm.BIZ_OPERATING_PREFIX + "NORMAL")
    await chat.reply(sm.BIZ_DAMAGE_PREFIX + "SIN_DANO")
    await chat.reply(sm.BTN_NO)
    await chat.reply(sm.SERVICES_PREFIX + "AGUA_LUZ")
    await chat.reply(sm.BIZ_SECTOR_PREFIX + "INDUSTRIA")
    await chat.reply(sm.BIZ_AGE_PREFIX + "1_3")
    await chat.reply(sm.BIZ_EMPLOYEES_PREFIX + "11_50")
    assert "solo un número" in bodies(await chat.text("muchos"))
    await chat.text("12")
    await chat.reply(sm.BIZ_TENURE_PREFIX + "PROPIO")
    await chat.reply(sm.BTN_NO)
    await chat.reply(sm.BIZ_REGISTRY_PREFIX + "RENOVADO")
    await chat.reply(sm.BIZ_LEGAL_FORM_PREFIX + "SOCIEDAD")
    assert "entre 5 y 15 dígitos" in bodies(await chat.text("12ab"))
    await chat.text("900123456")
    assert "No entendí" in bodies(await chat.text("tal vez"))  # RUT
    assert state_of(session_factory, chat) == State.WAITING_BIZ_RUT
    for _ in range(4):  # RUT, facturación, seguridad social, ICA
        await chat.reply(sm.BTN_YES)
    await chat.reply(sm.BTN_YES)  # predial
    await chat.reply(sm.BIZ_SALES_PREFIX + "MAS_100M")
    assert "No entendí" in bodies(await chat.text("9"))  # deudas: no existe la opción 9
    assert state_of(session_factory, chat) == State.WAITING_BIZ_DEBTS


async def test_necesidad_mas_urgente_debe_ser_una_de_las_marcadas(chat, session_factory):
    await start_business(chat)
    await business_block(chat, role="EMPLEADO", needs="1,2", top_need="SUBSIDIO")
    [(_, b)] = business_of(session_factory, chat.phone)
    assert (b.needs, b.urgent_need) == ("CREDITO,SUBSIDIO", "SUBSIDIO")

    await chat.text("cancelar")
    await chat.reply(sm.BTN_NEW_BUSINESS)
    await chat.reply(sm.BTN_YES)
    await location_block(chat)
    await chat.text("Tienda Dos")
    await chat.reply(sm.BIZ_ROLE_PREFIX + "OTRO")
    await chat.reply(sm.BIZ_PREMISES_PREFIX + "OFICINA")
    for _ in range(14):  # de "en vivienda" hasta el seguro
        await chat.text("saltar")
    await chat.text("4,5")
    assert "No entendí" in bodies(await chat.reply(sm.BIZ_TOP_NEED_PREFIX + "CREDITO"))  # no la marcó
    assert state_of(session_factory, chat) == State.WAITING_BIZ_TOP_NEED
    await chat.reply(sm.BIZ_TOP_NEED_PREFIX + "MAQUINARIA")
    [(_, b)] = business_of(session_factory, chat.phone)
    assert (b.needs, b.urgent_need) == ("REPARACION,MAQUINARIA", "MAQUINARIA")


# ---------------------------------------------------------------- vivienda + negocio


async def test_negocio_en_la_vivienda_ofrece_reportarla_con_la_misma_ubicacion(chat, session_factory, ocr):
    replies = await complete_business_report(chat, in_home=True)
    assert "Reportar mi vivienda" in bodies(replies)
    menu = replies[-1]
    assert isinstance(menu, ListMessage) and menu.rows[0][0] == sm.BTN_HOME_FROM_BUSINESS

    replies = await chat.reply(sm.BTN_HOME_FROM_BUSINESS)
    assert "misma ubicación" in bodies(replies) and "seguir viviendo" in replies[-1].body
    await situation_block(chat)
    await household_block(chat)
    assert state_of(session_factory, chat) == State.WAITING_DAMAGE_PHOTOS  # sin pedir de nuevo la identidad
    await chat.image("casa-1")
    replies = await chat.reply(sm.BTN_DONE)
    assert "visita a tu vivienda" in bodies(replies)
    assert all(row[0] != sm.BTN_HOME_FROM_BUSINESS for row in replies[-1].rows)  # ya la reportó
    assert len(ocr.calls) == 1  # la identidad se reutilizó

    (shop, _), (home, home_business) = business_of(session_factory, chat.phone)
    assert home.report_type == "VIVIENDA" and home_business is None
    for field in ("latitude", "longitude", "zone", "address_text", "municipality", "at_property"):
        assert getattr(home, field) == getattr(shop, field), field
    assert home.citizen_document_id == shop.citizen_document_id
    assert home.household_size == 4 and home.tenure == "ARRENDATARIO"


async def test_vivienda_y_luego_otro_negocio_reutiliza_la_identidad(chat, session_factory):
    from tests.test_flow import complete_report

    await complete_report(chat)
    replies = await chat.text("menu")
    rows = [row[0] for row in replies[-1].rows]
    assert sm.BTN_NEW_BUSINESS in rows and sm.BTN_HOME_FROM_BUSINESS not in rows
    replies = await chat.reply(sm.BTN_NEW_BUSINESS)
    assert "reporte de un negocio" in bodies(replies) and "en el negocio o local" in replies[-1].body
    await chat.reply(sm.BTN_YES)
    await location_block(chat)
    await business_block(chat)
    assert state_of(session_factory, chat) == State.WAITING_DAMAGE_PHOTOS  # identidad reutilizada
    await chat.image("local-x")
    await chat.reply(sm.BTN_DONE)
    (home, _), (shop, business) = business_of(session_factory, chat.phone)
    assert shop.report_type == "NEGOCIO" and business.legal_rep_document == home.citizen_document_id


async def test_cancelar_negocio_borra_sus_datos(chat, session_factory):
    await start_business(chat)
    await chat.text("Tienda Doña Rosa")
    await chat.text("cancelar")
    assert business_of(session_factory, chat.phone) == []
    with session_factory() as db:
        assert db.scalars(select(Business)).all() == []


async def test_alerta_nit_duplicado_entre_telefonos(bot, client, session_factory):
    a = Chat(bot, client, phone="573006660000")
    b = Chat(bot, client, phone="573007770000")
    await complete_business_report(a)
    await complete_business_report(b)
    [(report_b, _)] = business_of(session_factory, b.phone)
    assert AlertCode.NIT_DUPLICADO in alert_codes(report_b)


# ---------------------------------------------------------------- API pública


@pytest.fixture
def api(settings, client, session_factory):
    with TestClient(create_app(settings, client, session_factory)) as test_client:
        yield test_client


async def test_api_publica_de_negocios_sin_datos_reservados(bot, client, api):
    from tests.test_flow import complete_report

    await complete_report(Chat(bot, client, phone="573008880000"))
    await complete_business_report(Chat(bot, client, phone="573009990000"), debts="4", needs="1,6,3")
    await complete_business_report(
        Chat(bot, client, phone="573001010101"), role="EMPLEADO", losses="0", in_home=True, needs="1"
    )

    reports = api.get("/api/v1/reports/public").json()
    assert [r["report_type"] for r in reports] == ["NEGOCIO", "NEGOCIO", "VIVIENDA"]
    shop = reports[1]
    assert shop["business_sector"] == "COMERCIO" and shop["business_size"] == "MICRO"
    assert shop["business_closed"] is True and shop["jobs_at_risk"] == 3 and shop["structural_damage"] == "MENOR"
    assert shop["business_need"] == "CREDITO" and shop["business_needs"] == ["CREDITO", "INVENTARIO", "NOMINA"]
    assert reports[2]["business_sector"] is None and reports[2]["business_needs"] is None
    body = api.get("/api/v1/reports/public").text
    for secret in (
        "Doña Rosa", "9001234567", "5_20M", "20_50M", "MUJER", "1015234890", "legal_rep", "DUENO",
        "GOTA_A_GOTA", "BILLETERA", '"AL_DIA"', '"PENDIENTE"', "rut_status", "debts", "PERSONA_NATURAL",
    ):
        assert secret not in body, secret

    stats = api.get("/api/v1/reports/stats").json()
    assert stats["total_reports"] == 3 and stats["total_households"] == 1
    assert stats["people_affected"] == 4  # solo hogares
    b = stats["businesses"]
    assert (b["total"], b["closed"], b["jobs_at_risk"], b["sells_online"]) == (2, 2, 6, 2)
    assert (b["with_payment_account"], b["informal_lending"]) == (1, 1)  # solo el dueño responde finanzas
    assert b["by_need"]["CREDITO"] == 2 and b["by_need"]["NOMINA"] == 1 and b["by_need"]["INVENTARIO"] == 1
    assert b["by_top_need"]["CREDITO"] == 2
    assert b["needs_by_size"]["MICRO"]["CREDITO"] == 2 and b["needs_by_size"]["MEDIANA"]["CREDITO"] == 0
    assert b["by_structural_damage"]["MENOR"] == 2
    assert b["compliance"]["registro_mercantil"]["RENOVADO"] == 1
    assert b["compliance"]["rut"]["AL_DIA"] == 1 and b["compliance"]["seguridad_social"]["PENDIENTE"] == 1
    assert b["compliance"]["facturacion_electronica"]["NO_APLICA"] == 1
