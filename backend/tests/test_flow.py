from sqlalchemy import select

from app import content
from app.bot import state_manager as sm
from app.bot.messages import Buttons, ListMessage, LocationRequest, Text
from app.bot.states import State
from app.db.models import AlertCode, IdSource, MediaKind, Report, ReportStatus, User
from app.services.codes import ALPHABET
from app.services.ocr_service import IdData
from tests.conftest import Chat, bodies

# ---------------------------------------------------------------- recorridos por bloque


async def start_report(chat: Chat, at_property: bool = True) -> None:
    """Saludo → términos → ¿estás en la vivienda? (queda esperando la ubicación)."""
    await chat.text("Hola")
    await chat.reply(sm.BTN_ACCEPT)
    await chat.reply(sm.BTN_TYPE_HOME)
    await chat.reply(sm.BTN_YES if at_property else sm.BTN_NO)


async def location_block(chat: Chat, municipality: str = "Armenia, Quindío") -> None:
    await chat.location()
    await chat.reply(sm.BTN_ZONE_URBAN)
    await chat.text("Calle 10 # 5-23, barrio El Centro")
    await chat.text(municipality)


async def situation_block(chat: Chat, injured: bool = False) -> None:
    await chat.reply(sm.HABITABILITY_PREFIX + "HABITABLE_RIESGO")
    await chat.reply(sm.BTN_YES if injured else sm.BTN_NO)
    await chat.reply(sm.SERVICES_PREFIX + "SOLO_AGUA")
    await chat.reply(sm.URGENT_NEED_PREFIX + "ALIMENTOS")


async def household_block(chat: Chat) -> None:
    await chat.reply(sm.ESTRATO_PREFIX + "2")
    await chat.text("4")
    await chat.text("1,3")
    await chat.reply(sm.ETHNICITY_PREFIX + "NINGUNA")
    await chat.reply(sm.TENURE_PREFIX + "ARRENDATARIO")


async def reach_household(chat: Chat) -> None:
    """Hasta la pregunta del estrato."""
    await start_report(chat)
    await location_block(chat)
    await situation_block(chat)


async def reach_doc_type(chat: Chat, at_property: bool = True) -> None:
    await start_report(chat, at_property)
    await location_block(chat)
    await situation_block(chat)
    await household_block(chat)


async def reach_cedula(chat: Chat, at_property: bool = True) -> None:
    """Hasta el paso de la foto de la cédula."""
    await reach_doc_type(chat, at_property)
    await chat.reply(sm.DOC_TYPE_PREFIX + "CC")
    await chat.reply(sm.BTN_ID_PHOTO)


async def complete_report(chat: Chat, photo_ids=("dano-1",), at_property: bool = True) -> str:
    await reach_cedula(chat, at_property)
    await chat.image(f"cedula-{chat.phone}")
    await chat.reply(sm.BTN_ID_OK)
    for photo in photo_ids:
        await chat.image(photo)
    if len(photo_ids) < sm.MAX_DAMAGE_PHOTOS:
        await chat.reply(sm.BTN_DONE)
    return chat.phone


async def another_house_until_identity(chat: Chat) -> list:
    """Desde el menú: otra vivienda hasta después de la tenencia. Devuelve la última respuesta."""
    await chat.reply(sm.BTN_NEW)
    await chat.reply(sm.BTN_YES)
    await location_block(chat, "Calarcá")
    await situation_block(chat)
    await chat.text("1")  # estrato
    await chat.text("2")  # personas
    await chat.text("0")  # vulnerable: ninguno
    await chat.text("prefiero no responder")
    return await chat.text("propietario")


# ---------------------------------------------------------------- utilidades


def user_of(session_factory, phone: str) -> User:
    with session_factory() as db:
        return db.get(User, phone)


def reports_of(session_factory, phone: str) -> list[Report]:
    with session_factory() as db:
        reports = db.scalars(select(Report).where(Report.user_phone == phone).order_by(Report.id)).all()
        for r in reports:  # carga relaciones antes de cerrar la sesión
            _ = (r.alerts, r.media_files)
        return list(reports)


def alert_codes(report: Report) -> set[str]:
    return {a.code for a in report.alerts}


def state_of(session_factory, chat: Chat) -> str:
    return user_of(session_factory, chat.phone).state


# ---------------------------------------------------------------- camino feliz


async def test_camino_feliz_completo(chat, session_factory, settings):
    replies = await chat.text("Hola")
    assert "Hola Ana" in bodies(replies)
    assert isinstance(replies[-1], Buttons) and replies[-1].buttons[0][0] == sm.BTN_ACCEPT

    replies = await chat.reply(sm.BTN_ACCEPT)
    assert isinstance(replies[-1], Buttons) and replies[-1].buttons[1][0] == sm.BTN_TYPE_BUSINESS
    replies = await chat.reply(sm.BTN_TYPE_HOME)
    assert isinstance(replies[-1], Buttons) and "en la vivienda afectada" in replies[-1].body
    assert isinstance((await chat.reply(sm.BTN_YES))[-1], LocationRequest)
    replies = await chat.location(4.53, -75.68)
    assert isinstance(replies[-1], Buttons) and "zona urbana" in replies[-1].body
    assert "dirección" in bodies(await chat.reply(sm.BTN_ZONE_URBAN))
    replies = await chat.text("Calle 10 # 5-23, barrio El Centro")
    assert isinstance(replies[-1], ListMessage) and "municipio" in replies[-1].body

    # Situación de emergencia
    replies = await chat.text("Armenia, Quindío")
    assert isinstance(replies[-1], ListMessage) and "seguir viviendo" in replies[-1].body
    replies = await chat.reply(sm.HABITABILITY_PREFIX + "NO_ALBERGUE")
    assert isinstance(replies[-1], Buttons) and "heridas" in replies[-1].body
    replies = await chat.reply(sm.BTN_NO)
    assert "agua y luz" in replies[-1].body
    replies = await chat.reply(sm.SERVICES_PREFIX + "NINGUNO")
    assert "más necesita" in replies[-1].body
    replies = await chat.reply(sm.URGENT_NEED_PREFIX + "ALBERGUE")

    # Hogar
    assert "estrato" in replies[-1].body
    await chat.reply(sm.ESTRATO_PREFIX + "2")
    replies = await chat.text("4 personas")
    assert isinstance(replies[-1], Buttons) and "Víctimas del conflicto" in replies[-1].body
    replies = await chat.text("1, 5, 7")
    assert isinstance(replies[-1], ListMessage) and "étnicos" in replies[-1].body
    replies = await chat.reply(sm.ETHNICITY_PREFIX + "AFRO")
    assert isinstance(replies[-1], ListMessage) and "relación con la vivienda" in replies[-1].body

    # Identidad con cédula + OCR
    replies = await chat.reply(sm.TENURE_PREFIX + "ARRENDATARIO")
    assert "documento de identidad" in replies[-1].body
    replies = await chat.reply(sm.DOC_TYPE_PREFIX + "CC")
    assert isinstance(replies[-1], Buttons) and "a mano" in replies[-1].body
    assert "foto clara" in bodies(await chat.reply(sm.BTN_ID_PHOTO))
    replies = await chat.image("cedula-1")
    assert "ANA MARÍA PÉREZ" in bodies(replies) and "CC 1015234890" in bodies(replies)
    assert "fotos de los daños" in bodies(await chat.reply(sm.BTN_ID_OK))  # con foto de cédula no se pide selfie

    # Daños
    replies = await chat.image("dano-1")
    assert isinstance(replies[-1], Buttons) and replies[-1].buttons == ((sm.BTN_DONE, "Listo"),)
    await chat.image("dano-2")
    replies = await chat.reply(sm.BTN_DONE)
    assert "Tu reporte quedó registrado" in bodies(replies)
    assert isinstance(replies[-1], ListMessage)  # menú

    user = user_of(session_factory, chat.phone)
    assert user.state == State.COMPLETED
    assert user.id_source == IdSource.OCR and user.id_confirmed and user.document_type == "CC"
    assert user.terms_accepted_at is not None and user.selfie_consent_at is None

    [report] = reports_of(session_factory, chat.phone)
    assert report.status == ReportStatus.PENDIENTE_REVISION
    assert (report.latitude, report.longitude) == (4.53, -75.68)
    assert report.at_property is True and report.zone == "URBANA"
    assert report.skipped_questions is None
    assert report.address_text == "Calle 10 # 5-23, barrio El Centro"
    assert report.municipality == "Armenia, Quindío"
    assert (report.habitability, report.injured, report.services, report.urgent_need) == (
        "NO_ALBERGUE", False, "NINGUNO", "ALBERGUE"
    )
    assert (report.estrato, report.household_size, report.ethnicity) == ("2", 4, "AFRO")
    assert report.vulnerable_groups == "NINOS,VICTIMA_CONFLICTO,JEFATURA_FEMENINA"
    assert report.tenure == "ARRENDATARIO"
    assert (report.citizen_document_type, report.citizen_document_id) == ("CC", "1015234890")
    assert report.damage_level == "AMARILLO"
    assert len(report.confirmation_code) == 8 and set(report.confirmation_code) <= set(ALPHABET)
    assert report.confirmation_code in bodies(replies)
    assert [m.kind for m in report.media_files] == [MediaKind.CEDULA, MediaKind.DANO, MediaKind.DANO]
    assert all((settings.MEDIA_DIR / m.path).is_file() for m in report.media_files)
    assert alert_codes(report) == {AlertCode.SIN_VIVIENDA}


# ---------------------------------------------------------------- situación y hogar


async def test_listas_aceptan_numero_o_nombre_escrito(chat, session_factory):
    await start_report(chat)
    await location_block(chat)
    await chat.text("3")  # habitabilidad: opción 3 = No: en un albergue
    await chat.text("no")  # heridos
    await chat.text("solo luz")  # servicios por nombre
    await chat.text("medicamentos")  # necesidad por nombre
    await chat.text("Rural / sin estrato")
    [report] = reports_of(session_factory, chat.phone)
    assert (report.habitability, report.services, report.urgent_need, report.estrato) == (
        "NO_ALBERGUE", "SOLO_LUZ", "MEDICAMENTOS", "RURAL"
    )
    assert state_of(session_factory, chat) == State.WAITING_HOUSEHOLD


async def test_opcion_invalida_en_lista_repite_la_pregunta(chat, session_factory):
    await start_report(chat)
    await location_block(chat)
    replies = await chat.text("quién sabe")
    assert "No entendí" in bodies(replies) and isinstance(replies[-1], ListMessage)
    assert state_of(session_factory, chat) == State.WAITING_HABITABILITY


async def test_heridos_da_la_linea_123_y_alerta_prioritaria(chat, session_factory):
    await start_report(chat)
    await location_block(chat)
    await chat.reply(sm.HABITABILITY_PREFIX + "HABITABLE")
    replies = await chat.reply(sm.BTN_YES)
    assert "llama ya a la línea de emergencias 123" in bodies(replies)
    [report] = reports_of(session_factory, chat.phone)
    assert report.injured is True
    assert AlertCode.HERIDOS in alert_codes(report)
    assert AlertCode.SIN_VIVIENDA not in alert_codes(report)  # sí pueden habitarla


async def test_entrada_invalida_repite_la_pregunta_sin_perder_el_estado(chat, session_factory):
    await reach_household(chat)
    await chat.reply(sm.ESTRATO_PREFIX + "3")
    replies = await chat.text("muchos")
    assert "entre 1 y 30" in bodies(replies)
    assert "Cuántas personas" in bodies(replies)
    assert state_of(session_factory, chat) == State.WAITING_HOUSEHOLD


async def test_hogar_desde_la_lista_y_seis_o_mas(chat, session_factory):
    await reach_household(chat)
    await chat.reply(sm.ESTRATO_PREFIX + "1")
    replies = await chat.reply(sm.HOUSEHOLD_PREFIX + content.HOUSEHOLD_MORE_ID)
    assert "número exacto" in bodies(replies)
    await chat.text("9")
    [report] = reports_of(session_factory, chat.phone)
    assert report.household_size == 9
    assert state_of(session_factory, chat) == State.WAITING_VULNERABLE


async def test_poblacion_vulnerable_si_luego_cuales_y_no(chat, session_factory):
    await reach_household(chat)
    await chat.reply(sm.ESTRATO_PREFIX + "1")
    await chat.reply(sm.HOUSEHOLD_PREFIX + "3")
    assert "Cuáles" in bodies(await chat.reply(sm.BTN_YES))
    assert "No entendí" in bodies(await chat.text("9"))
    await chat.text("2,6,8,2")
    [report] = reports_of(session_factory, chat.phone)
    assert report.vulnerable_groups == "ADULTOS_MAYORES,MIGRANTE,ENFERMEDAD_CRONICA"
    assert state_of(session_factory, chat) == State.WAITING_ETHNICITY

    await chat.text("cancelar")
    await chat.reply(sm.BTN_NEW)
    await chat.reply(sm.BTN_YES)
    await location_block(chat)
    await situation_block(chat)
    await chat.reply(sm.ESTRATO_PREFIX + "1")
    await chat.reply(sm.HOUSEHOLD_PREFIX + "1")
    await chat.reply(sm.BTN_NO)
    [report] = reports_of(session_factory, chat.phone)
    assert report.vulnerable_groups == "NINGUNO"


async def test_etnia_prefiero_no_responder(chat, session_factory):
    await reach_household(chat)
    await chat.reply(sm.ESTRATO_PREFIX + "NO_SABE")
    await chat.reply(sm.HOUSEHOLD_PREFIX + "2")
    await chat.reply(sm.BTN_NO)
    await chat.reply(sm.ETHNICITY_PREFIX + "NO_RESPONDE")
    [report] = reports_of(session_factory, chat.phone)
    assert (report.estrato, report.ethnicity) == ("NO_SABE", "NO_RESPONDE")
    assert state_of(session_factory, chat) == State.WAITING_TENURE


# ---------------------------------------------------------------- ubicación


async def test_respuestas_escritas_equivalen_a_botones(chat, session_factory):
    await chat.text("Buenas")
    await chat.text("¡Sí, acepto!")
    await chat.text("vivienda")
    await chat.text("no")
    assert state_of(session_factory, chat) == State.WAITING_LOCATION
    [report] = reports_of(session_factory, chat.phone)
    assert report.at_property is False


async def test_omitir_gps_agrega_alerta(chat, session_factory):
    await start_report(chat)
    replies = await chat.text("Omitir")
    assert "sin la ubicación" in bodies(replies)
    [report] = reports_of(session_factory, chat.phone)
    assert AlertCode.SIN_GPS in alert_codes(report)
    assert report.latitude is None


async def test_texto_en_lugar_de_ubicacion_explica_como_enviarla(chat):
    await start_report(chat)
    replies = await chat.text("estoy en la casa")
    assert "tiempo real" in bodies(replies)
    assert isinstance(replies[-1], LocationRequest)


async def test_gps_lejos_de_la_vivienda_queda_como_alerta_informativa(chat, session_factory):
    await complete_report(chat, at_property=False)
    [report] = reports_of(session_factory, chat.phone)
    assert AlertCode.GPS_FUERA_DE_VIVIENDA in alert_codes(report)


async def test_municipio_desde_la_lista_y_otro(chat, session_factory):
    await start_report(chat)
    await chat.location()
    await chat.reply(sm.BTN_ZONE_URBAN)
    replies = await chat.text("Calle 1 # 2-3")
    page1 = replies[-1]
    assert isinstance(page1, ListMessage)
    titles = [title for _, title, _ in page1.rows]
    assert titles[:2] == ["Armenia", "Bogotá"] and "Medellín" in titles and "Manizales" in titles
    assert titles[-1] == "Ver más municipios" and len(page1.rows) == 10
    await chat.reply(sm.MUNICIPALITY_PREFIX + "BOGOTA")
    [report] = reports_of(session_factory, chat.phone)
    assert report.municipality == "Bogotá, Distrito Capital"

    await chat.text("cancelar")
    await chat.reply(sm.BTN_NEW)
    await chat.reply(sm.BTN_YES)
    await chat.location()
    await chat.reply(sm.BTN_ZONE_URBAN)
    await chat.text("Calle 1 # 2-3")
    [page2] = await chat.reply(sm.MUNICIPALITY_PREFIX + content.MUNICIPALITY_MORE_ID)
    assert isinstance(page2, ListMessage)
    titles = [title for _, title, _ in page2.rows]
    assert "Pereira" in titles and "Popayán" in titles and titles[-1] == "Otro municipio"
    assert state_of(session_factory, chat) == State.WAITING_MUNICIPALITY
    await chat.reply(sm.MUNICIPALITY_PREFIX + "PEREIRA")
    [report] = reports_of(session_factory, chat.phone)
    assert report.municipality == "Pereira, Risaralda"

    await chat.text("cancelar")
    await chat.reply(sm.BTN_NEW)
    await chat.reply(sm.BTN_YES)
    await chat.location()
    await chat.reply(sm.BTN_ZONE_URBAN)
    await chat.text("Calle 1 # 2-3")
    replies = await chat.reply(sm.MUNICIPALITY_PREFIX + content.MUNICIPALITY_OTHER_ID)
    assert "Escribe el *municipio" in bodies(replies)
    assert state_of(session_factory, chat) == State.WAITING_MUNICIPALITY
    await chat.text("Timbío, Cauca")
    [report] = reports_of(session_factory, chat.phone)
    assert report.municipality == "Timbío, Cauca"


async def test_zona_rural_pide_vereda_y_pueblo_cercano_y_no_pregunta_estrato(chat, session_factory):
    await start_report(chat)
    await chat.location()
    replies = await chat.text("rural")
    assert "vereda o corregimiento" in bodies(replies)
    replies = await chat.text("Finca La Esperanza, vereda El Retiro")
    assert "pueblo o municipio más cercano" in bodies(replies)
    assert not isinstance(replies[-1], ListMessage)  # en zona rural se escribe, no hay lista
    await chat.text("Timbío, Cauca")
    await situation_block(chat)  # la necesidad urgente lleva directo a personas del hogar
    assert state_of(session_factory, chat) == State.WAITING_HOUSEHOLD
    [report] = reports_of(session_factory, chat.phone)
    assert report.zone == "RURAL"
    assert report.address_text == "Finca La Esperanza, vereda El Retiro"
    assert report.municipality == "Timbío, Cauca"
    assert report.estrato == "RURAL"


async def test_zona_obligatoria_no_se_puede_saltar(chat, session_factory):
    await start_report(chat)
    await chat.location()
    replies = await chat.text("saltar")
    assert "No entendí" in bodies(replies)
    assert state_of(session_factory, chat) == State.WAITING_ZONE


# ---------------------------------------------------------------- saltar preguntas


async def test_saltar_preguntas_opcionales_queda_registrado(chat, session_factory):
    await start_report(chat)
    await chat.location()
    await chat.reply(sm.BTN_ZONE_URBAN)
    replies = await chat.text("saltar")  # dirección
    assert "siguiente pregunta" in bodies(replies)
    assert isinstance(replies[-1], ListMessage)  # municipio (obligatorio, sin opción de saltar)
    assert all(row[0] != sm.BTN_SKIP for row in replies[-1].rows)
    await chat.reply(sm.MUNICIPALITY_PREFIX + "CALI")
    await chat.reply(sm.BTN_SKIP)  # habitabilidad (fila de la lista)
    await chat.reply(sm.BTN_SKIP)  # heridos (botón)
    await chat.text("Saltar")  # servicios (escrito)
    await chat.reply(sm.URGENT_NEED_PREFIX + "AGUA")
    await chat.text("omitir")  # estrato
    await chat.reply(sm.BTN_SKIP)  # personas del hogar
    await chat.reply(sm.BTN_YES)  # población vulnerable: sí...
    await chat.text("saltar")  # ...pero no dice cuáles
    await chat.text("saltar")  # etnia
    replies = await chat.reply(sm.BTN_SKIP)  # tenencia
    assert "documento de identidad" in replies[-1].body

    [report] = reports_of(session_factory, chat.phone)
    assert report.skipped_questions == (
        "direccion,habitabilidad,heridos,servicios,estrato,personas_hogar,"
        "poblacion_vulnerable,pertenencia_etnica,tenencia"
    )
    assert report.address_text is None and report.habitability is None and report.injured is None
    assert report.services is None and report.estrato is None and report.household_size is None
    assert report.vulnerable_groups is None and report.ethnicity is None and report.tenure is None
    assert report.urgent_need == "AGUA" and report.municipality == "Cali, Valle del Cauca"
    assert AlertCode.SIN_VIVIENDA not in alert_codes(report) and AlertCode.HERIDOS not in alert_codes(report)


async def test_saltar_no_aplica_en_terminos_ni_identidad(chat, session_factory):
    await chat.text("hola")
    replies = await chat.text("saltar")
    assert "No entendí" in bodies(replies)
    assert state_of(session_factory, chat) == State.WAITING_TERMS

    await chat.reply(sm.BTN_ACCEPT)
    await chat.reply(sm.BTN_TYPE_HOME)
    await chat.reply(sm.BTN_YES)
    await location_block(chat)
    await situation_block(chat)
    await household_block(chat)
    replies = await chat.text("saltar")
    assert "No entendí" in bodies(replies)
    assert state_of(session_factory, chat) == State.WAITING_DOC_TYPE


# ---------------------------------------------------------------- identidad


async def test_cedula_sin_foto_numero_escrito_y_selfie(chat, session_factory, settings, ocr):
    await reach_doc_type(chat)
    await chat.reply(sm.DOC_TYPE_PREFIX + "CC")
    replies = await chat.reply(sm.BTN_ID_NOPHOTO)
    assert "nombre completo" in bodies(replies)
    replies = await chat.text("Laura Gómez Ruiz")
    assert "número de tu cédula de ciudadanía" in bodies(replies)
    replies = await chat.text("1.032.456.789")
    assert isinstance(replies[-1], Buttons) and "biométrico" in replies[-1].body
    assert "selfie de frente" in bodies(await chat.reply(sm.BTN_SELFIE_YES))
    replies = await chat.image("selfie-1")
    assert "recibimos tu foto" in bodies(replies) and "fotos de los daños" in bodies(replies)
    await chat.image("dano-1")
    await chat.reply(sm.BTN_DONE)

    assert ocr.calls == []  # sin foto de cédula no se usa el OCR
    user = user_of(session_factory, chat.phone)
    assert (user.document_type, user.document_id, user.id_source) == ("CC", "1032456789", IdSource.MANUAL)
    assert user.selfie_consent_at is not None
    [report] = reports_of(session_factory, chat.phone)
    assert [m.kind for m in report.media_files] == [MediaKind.SELFIE, MediaKind.DANO]
    assert all((settings.MEDIA_DIR / m.path).is_file() for m in report.media_files)
    assert report.citizen_document_id == "1032456789"


async def test_rechazar_selfie_continua_sin_ella(chat, session_factory):
    await reach_doc_type(chat)
    await chat.reply(sm.DOC_TYPE_PREFIX + "PPT")
    await chat.text("José Pérez Díaz")
    replies = await chat.text("4455667")
    assert "biométrico" in bodies(replies)
    replies = await chat.reply(sm.BTN_SELFIE_NO)
    assert "sin la foto" in bodies(replies) and "fotos de los daños" in bodies(replies)
    user = user_of(session_factory, chat.phone)
    assert (user.document_type, user.document_id) == ("PPT", "4455667")
    assert user.selfie_consent_at is None
    assert state_of(session_factory, chat) == State.WAITING_DAMAGE_PHOTOS


async def test_selfie_autorizada_pero_omitida(chat, session_factory):
    await reach_doc_type(chat)
    await chat.reply(sm.DOC_TYPE_PREFIX + "CE")
    await chat.text("Ana Pérez Ruiz")
    await chat.text("654321")
    await chat.reply(sm.BTN_SELFIE_YES)
    assert "sin la foto" in bodies(await chat.text("omitir"))
    assert state_of(session_factory, chat) == State.WAITING_DAMAGE_PHOTOS


async def test_pasaporte_acepta_letras_y_otros_documentos_no(chat, session_factory):
    await reach_doc_type(chat)
    await chat.reply(sm.DOC_TYPE_PREFIX + "PASAPORTE")
    replies = await chat.text("Pedro Pérez Silva")
    assert "número de tu pasaporte" in bodies(replies)
    replies = await chat.text("ab-1234567")
    assert "biométrico" in bodies(replies)
    assert user_of(session_factory, chat.phone).document_id == "AB1234567"


async def test_tarjeta_de_identidad_rechaza_letras(chat, session_factory):
    await reach_doc_type(chat)
    await chat.reply(sm.DOC_TYPE_PREFIX + "TI")
    replies = await chat.text("María Pérez Ruiz")
    assert "número de tu tarjeta de identidad" in bodies(replies)
    replies = await chat.text("AB12345")
    assert "entre 5 y 12 dígitos" in bodies(replies)
    assert state_of(session_factory, chat) == State.WAITING_MANUAL_DOCUMENT


async def test_sin_documento_solo_nombre_y_alerta(chat, session_factory):
    await reach_doc_type(chat)
    await chat.text("no tengo documento")  # también por nombre escrito
    await chat.text("Rosa Elena Quintero")
    replies = await chat.reply(sm.BTN_SELFIE_NO)
    assert "fotos de los daños" in bodies(replies)
    await chat.image("dano-1")
    await chat.reply(sm.BTN_DONE)
    user = user_of(session_factory, chat.phone)
    assert (user.document_type, user.document_id, user.full_name) == ("NINGUNO", None, "ROSA ELENA QUINTERO")
    [report] = reports_of(session_factory, chat.phone)
    assert report.status == ReportStatus.PENDIENTE_REVISION
    assert report.citizen_document_type == "NINGUNO" and report.citizen_document_id is None
    assert AlertCode.SIN_DOCUMENTO in alert_codes(report)


async def test_foto_directa_en_la_pregunta_de_metodo_se_lee_como_cedula(chat, session_factory, ocr):
    await reach_doc_type(chat)
    await chat.reply(sm.DOC_TYPE_PREFIX + "CC")
    await chat.image("ced-directa")
    assert len(ocr.calls) == 1
    assert state_of(session_factory, chat) == State.WAITING_ID_CONFIRM


async def test_ocr_ilegible_dos_veces_pasa_a_datos_manuales(chat, session_factory, ocr):
    ocr.result = IdData(full_name=None, document_id=None)
    await reach_cedula(chat)

    assert "No pudimos leer" in bodies(await chat.image("ced-a"))
    replies = await chat.image("ced-b")
    assert "nombre completo" in bodies(replies)
    assert "nombres y apellidos" in bodies(await chat.text("Juan"))  # una sola palabra no basta
    await chat.text("juan  pérez gómez")
    await chat.text("1.020.304.050")

    user = user_of(session_factory, chat.phone)
    assert user.state == State.WAITING_DAMAGE_PHOTOS  # envió fotos de cédula: no se pide selfie
    assert (user.full_name, user.document_id, user.id_source) == ("JUAN PÉREZ GÓMEZ", "1020304050", IdSource.MANUAL)
    [report] = reports_of(session_factory, chat.phone)
    assert AlertCode.OCR_ILEGIBLE in alert_codes(report)


async def test_documento_invalido_se_rechaza(chat, session_factory, ocr):
    await reach_cedula(chat)
    await chat.image("ced")
    await chat.reply(sm.BTN_ID_FIX)
    await chat.text("Ana Pérez")
    replies = await chat.text("12a45")
    assert "entre 5 y 12 dígitos" in bodies(replies)
    assert state_of(session_factory, chat) == State.WAITING_MANUAL_DOCUMENT


async def test_corregir_datos_del_ocr(chat, session_factory):
    await reach_cedula(chat)
    await chat.image("ced")
    await chat.reply(sm.BTN_ID_FIX)
    await chat.text("Ana Pérez Ruiz")
    await chat.text("1015234899")
    user = user_of(session_factory, chat.phone)
    assert user.document_id == "1015234899" and user.id_source == IdSource.MANUAL
    assert user.state == State.WAITING_DAMAGE_PHOTOS
    [report] = reports_of(session_factory, chat.phone)
    assert AlertCode.DATOS_CORREGIDOS in alert_codes(report)


async def test_pdf_en_lugar_de_foto_se_rechaza(chat, session_factory, ocr):
    await reach_cedula(chat)
    replies = await chat.document("pdf-1", "application/pdf")
    assert "PDF" in bodies(replies)
    assert ocr.calls == []
    assert state_of(session_factory, chat) == State.WAITING_CEDULA


async def test_foto_enviada_como_documento_se_acepta(chat, session_factory):
    await reach_cedula(chat)
    await chat.document("ced-doc", "image/jpeg")
    assert state_of(session_factory, chat) == State.WAITING_ID_CONFIRM


async def test_fallo_de_descarga_pide_reenviar(chat, client, session_factory):
    await reach_cedula(chat)
    client.fail_download = True
    assert "enviarla de nuevo" in bodies(await chat.image("ced"))
    assert state_of(session_factory, chat) == State.WAITING_CEDULA


# ---------------------------------------------------------------- fotos y envío


async def test_tres_fotos_envian_el_reporte_automaticamente(chat, session_factory):
    await reach_cedula(chat)
    await chat.image("ced")
    await chat.reply(sm.BTN_ID_OK)
    await chat.image("d1")
    await chat.image("d2")
    replies = await chat.image("d3")
    assert "Tu reporte quedó registrado" in bodies(replies)
    [report] = reports_of(session_factory, chat.phone)
    assert sum(m.kind == MediaKind.DANO for m in report.media_files) == 3


async def test_listo_sin_fotos_no_envia(chat, session_factory):
    await reach_cedula(chat)
    await chat.image("ced")
    await chat.reply(sm.BTN_ID_OK)
    assert "al menos una foto" in bodies(await chat.text("listo"))
    assert state_of(session_factory, chat) == State.WAITING_DAMAGE_PHOTOS


async def test_avisos_inmediatos_antes_de_procesos_lentos(chat):
    await reach_cedula(chat)
    assert "Estamos leyendo tu cédula" in bodies(await chat.image("ced"))
    await chat.reply(sm.BTN_ID_OK)
    await chat.image("d1")
    assert "analizando las fotos" in bodies(await chat.reply(sm.BTN_DONE))


# ---------------------------------------------------------------- comandos y menú


async def test_cancelar_descarta_borrador_y_fotos(chat, session_factory, settings):
    await reach_cedula(chat)
    await chat.image("ced")
    assert any(settings.MEDIA_DIR.rglob("*.jpg"))
    replies = await chat.text("Cancelar")
    assert "descartamos" in bodies(replies)
    assert reports_of(session_factory, chat.phone) == []
    assert not any(settings.MEDIA_DIR.rglob("*.jpg"))
    assert state_of(session_factory, chat) == State.COMPLETED


async def test_rechazar_terminos(chat, session_factory):
    await chat.text("hola")
    replies = await chat.reply(sm.BTN_REJECT)
    assert "Sin tu autorización" in bodies(replies)
    user = user_of(session_factory, chat.phone)
    assert user.state == State.START and user.terms_accepted_at is None
    assert reports_of(session_factory, chat.phone) == []


async def test_ayuda_no_cambia_el_estado(chat, session_factory):
    await chat.text("hola")
    assert "cancelar" in bodies(await chat.text("ayuda"))
    assert state_of(session_factory, chat) == State.WAITING_TERMS


async def test_menu_ver_estado_y_hablar_con_persona(chat, session_factory):
    await complete_report(chat)
    [report] = reports_of(session_factory, chat.phone)
    replies = await chat.reply(sm.BTN_STATUS)
    assert report.confirmation_code in bodies(replies) and "En revisión" in bodies(replies)
    assert "123" in bodies(await chat.reply(sm.BTN_HUMAN))
    replies = await chat.text("hola de nuevo")
    assert isinstance(replies[-1], ListMessage) and replies[-1].rows[0][0] == sm.BTN_STATUS


async def test_menu_enlaces_a_la_web(chat):
    await complete_report(chat)
    for button, path in (
        (sm.BTN_COLLECTION, "/centros-de-acopio"),
        (sm.BTN_MISSING, "/desaparecidos"),
        (sm.BTN_HELP_OTHERS, "/voluntariado"),
    ):
        [reply] = await chat.reply(button)
        assert isinstance(reply, Text) and reply.preview_url
        assert content.WEB_URL + path in reply.body


async def test_menu_sin_reportes_no_ofrece_ver_estado(chat):
    await chat.text("hola")
    await chat.reply(sm.BTN_ACCEPT)
    replies = await chat.text("cancelar")
    menu = replies[-1]
    assert isinstance(menu, ListMessage)
    ids = [row[0] for row in menu.rows]
    assert sm.BTN_STATUS not in ids and ids[0] == sm.BTN_NEW


async def test_reiniciar_demo_solo_desde_celulares_del_stand(bot, client, settings, session_factory):
    stand_phone = "573005550000"
    bot._settings = settings.model_copy(update={"DEMO_PHONES": "+57 300 555 0000, 573009990000"})
    stand = Chat(bot, client, phone=stand_phone, name="Dueño Del Celular")
    visitor = Chat(bot, client, phone="573001112222", name="Visitante")

    replies = await stand.text("hola")
    assert "Dueño" not in bodies(replies)  # en el stand no se saluda con el nombre del perfil
    await complete_report(stand)
    await stand.reply(sm.BTN_NEW)  # deja un borrador a medias
    await stand.reply(sm.BTN_YES)

    replies = await stand.text("Reiniciar demo")
    assert "Demo reiniciada" in bodies(replies)
    assert isinstance(replies[-1], Buttons) and replies[-1].buttons[0][0] == sm.BTN_ACCEPT
    user = user_of(session_factory, stand_phone)
    assert user.state == State.WAITING_TERMS
    assert user.terms_accepted_at is None and user.document_id is None and user.document_type is None
    assert not user.id_confirmed and user.selfie_consent_at is None
    reports = reports_of(session_factory, stand_phone)
    assert [r.status for r in reports] == [ReportStatus.PENDIENTE_REVISION]  # el enviado se conserva, el borrador no

    # Un visitante normal no puede reiniciar y sí ve su nombre
    assert "Visitante" in bodies(await visitor.text("hola"))
    replies = await visitor.text("reiniciar demo")
    assert "Demo reiniciada" not in bodies(replies)
    assert state_of(session_factory, visitor) == State.WAITING_TERMS


async def test_otra_vivienda_reutiliza_la_identidad(chat, session_factory, ocr):
    await complete_report(chat)
    replies = await another_house_until_identity(chat)
    assert "ya registraste" in bodies(replies)
    assert len(ocr.calls) == 1
    await chat.image("dano-otra")
    await chat.reply(sm.BTN_DONE)

    first, second = reports_of(session_factory, chat.phone)
    assert second.status == ReportStatus.PENDIENTE_REVISION
    assert second.tenure == "PROPIETARIO" and second.vulnerable_groups == "NINGUNO"
    assert second.ethnicity == "NO_RESPONDE" and second.estrato == "1"
    assert second.citizen_document_id == first.citizen_document_id
    assert second.confirmation_code != first.confirmation_code
    assert alert_codes(second) == set()  # misma persona, mismo teléfono: no es duplicado


async def test_otra_vivienda_sin_documento_mantiene_la_alerta(chat, session_factory):
    await reach_doc_type(chat)
    await chat.reply(sm.DOC_TYPE_PREFIX + "NINGUNO")
    await chat.text("Rosa Elena Quintero")
    await chat.reply(sm.BTN_SELFIE_NO)
    await chat.image("dano-1")
    await chat.reply(sm.BTN_DONE)
    replies = await another_house_until_identity(chat)
    assert "ya registraste" in bodies(replies)
    await chat.image("dano-2")
    await chat.reply(sm.BTN_DONE)
    _, second = reports_of(session_factory, chat.phone)
    assert AlertCode.SIN_DOCUMENTO in alert_codes(second)


# ---------------------------------------------------------------- robustez y alertas


async def test_mensaje_duplicado_de_meta_se_ignora(bot, client):
    from app.bot.schemas import IncomingMessage, MessageKind

    msg = IncomingMessage(wamid="wamid.repetido", from_phone="573009999999", kind=MessageKind.TEXT, text="hola")
    await bot.handle(msg)
    sent = len(client.sent)
    await bot.handle(msg)
    assert len(client.sent) == sent


async def test_alerta_cedula_duplicada_entre_telefonos(bot, client, session_factory):
    a = Chat(bot, client, phone="573001111111")
    b = Chat(bot, client, phone="573002222222")
    await complete_report(a)
    await complete_report(b)  # el FakeOcr devuelve la misma cédula para ambos
    [report_b] = reports_of(session_factory, b.phone)
    assert AlertCode.CEDULA_DUPLICADA in alert_codes(report_b)


async def test_alerta_foto_repetida(bot, client, session_factory):
    a = Chat(bot, client, phone="573003333333")
    b = Chat(bot, client, phone="573004444444")
    await complete_report(a, photo_ids=("misma-foto",))
    await complete_report(b, photo_ids=("misma-foto",))
    [report_b] = reports_of(session_factory, b.phone)
    assert AlertCode.FOTO_REPETIDA in alert_codes(report_b)
