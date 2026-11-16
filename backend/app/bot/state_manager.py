"""Máquina de estados de la conversación de GeoAid.

Cada mensaje entrante se procesa así:
1. Se descarta si ya se procesó (Meta puede reenviar el mismo webhook).
2. Se atienden los comandos globales (cancelar, ayuda).
3. El handler del estado actual valida la entrada, guarda datos y cambia de estado.
4. Se confirma la transacción y solo entonces se envían las respuestas.
"""

import asyncio
import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import content
from app.bot.messages import Buttons, ListMessage, LocationRequest, Outgoing, Text
from app.bot.meta_client import DownloadedMedia, MetaAPIError
from app.bot.schemas import IncomingMessage, MessageKind
from app.bot.states import State
from app.config import Settings
from app.db.models import (
    AlertCode,
    Business,
    IdSource,
    MediaFile,
    MediaKind,
    ProcessedMessage,
    Report,
    ReportStatus,
    User,
    VulnerableGroup,
)
from app.services import alerts, codes, media_service, ocr_service, vision_service
from app.services.ocr_service import IdData
from app.services.vision_service import DamageAssessment

logger = logging.getLogger(__name__)

MAX_DAMAGE_PHOTOS = 3
MAX_OCR_ATTEMPTS = 2

# Ids de botones y listas
BTN_ACCEPT = "terms:accept"
BTN_REJECT = "terms:reject"
BTN_YES = "answer:yes"
BTN_NO = "answer:no"
BTN_ID_OK = "id:ok"
BTN_ID_FIX = "id:fix"
BTN_DONE = "photos:done"
BTN_STATUS = "menu:status"
BTN_NEW = "menu:new"
BTN_HUMAN = "menu:human"
BTN_COLLECTION = "menu:acopio"
BTN_MISSING = "menu:desaparecidos"
BTN_HELP_OTHERS = "menu:ayudar"
BTN_ID_PHOTO = "id:photo"
BTN_ID_NOPHOTO = "id:nophoto"
BTN_SELFIE_YES = "selfie:yes"
BTN_SELFIE_NO = "selfie:no"
BTN_ZONE_URBAN = "zone:urban"
BTN_ZONE_RURAL = "zone:rural"
BTN_SKIP = "skip"  # botón o fila "Saltar pregunta" (sin prefijo: se reconoce en cualquier pregunta)
BTN_UNKNOWN = "answer:unknown"
BTN_TYPE_HOME = "type:home"
BTN_TYPE_BUSINESS = "type:business"
BTN_NEW_BUSINESS = "menu:new_business"
BTN_HOME_FROM_BUSINESS = "menu:home_from_business"
BTN_NOT_APPLICABLE = "answer:not_applicable"
TENURE_PREFIX = "tenure:"
MUNICIPALITY_PREFIX = "muni:"
HOUSEHOLD_PREFIX = "household:"
HABITABILITY_PREFIX = "habit:"
SERVICES_PREFIX = "services:"
URGENT_NEED_PREFIX = "need:"
ESTRATO_PREFIX = "estrato:"
ETHNICITY_PREFIX = "ethnic:"
DOC_TYPE_PREFIX = "doc:"
BIZ_PREMISES_PREFIX = "premises:"
BIZ_OPERATING_PREFIX = "operating:"
BIZ_SECTOR_PREFIX = "sector:"
BIZ_AGE_PREFIX = "age:"
BIZ_EMPLOYEES_PREFIX = "employees:"
BIZ_REGISTRY_PREFIX = "registry:"
BIZ_TENURE_PREFIX = "biztenure:"
BIZ_SALES_PREFIX = "sales:"
BIZ_LOSS_VALUE_PREFIX = "lossvalue:"
BIZ_ROLE_PREFIX = "role:"
BIZ_DAMAGE_PREFIX = "damage:"
BIZ_REOPENING_PREFIX = "reopening:"
BIZ_LEGAL_FORM_PREFIX = "legalform:"
BIZ_PAYMENT_PREFIX = "payment:"
BIZ_TOP_NEED_PREFIX = "topneed:"
MAX_CONCURRENT_ANALYSIS = 2
HOME = content.REPORT_TYPE_HOME
BUSINESS = content.REPORT_TYPE_BUSINESS

# Equivalentes escritos (ya normalizados: minúsculas y sin tildes)
ACCEPT_WORDS = {"acepto", "si", "si acepto", "autorizo", "1"}
REJECT_WORDS = {"no acepto", "no", "no autorizo", "2"}
YES_WORDS = {"si", "s", "claro", "correcto", "1"}
NO_WORDS = {"no", "n", "2"}
FIX_WORDS = NO_WORDS | {"corregir", "estan mal"}
CANCEL_WORDS = {"cancelar", "cancela"}
HELP_WORDS = {"ayuda"}
SKIP_WORDS = {"omitir", "omito", "no puedo"}
DONE_WORDS = {"listo", "terminar", "termine", "ya"}
NONE_WORDS = {"0", "ninguno", "ninguna", "ningun", "no", "nadie"}
STATUS_WORDS = {"estado", "ver estado"}
NEW_WORDS = {"nuevo", "nuevo reporte", "otra", "otra vivienda", "reportar"}
HUMAN_WORDS = {"persona", "hablar con persona", "humano", "asesor"}
DEMO_RESET_WORDS = {"reiniciar demo"}
NO_PHOTO_WORDS = NO_WORDS | {"no la tengo", "no tengo", "escribir", "la escribo"}
PHOTO_WORDS = YES_WORDS | {"foto", "enviar foto", "si enviar foto"}
SELFIE_NO_WORDS = NO_WORDS | SKIP_WORDS | {"no continuar", "no autorizo"}
SELFIE_YES_WORDS = YES_WORDS | {"si autorizo", "autorizo", "acepto"}
URBAN_WORDS = {"urbana", "urbano", "zona urbana", "ciudad", "pueblo", "casco urbano", "1"}
RURAL_WORDS = {"rural", "zona rural", "vereda", "finca", "campo", "corregimiento", "2"}
SKIP_QUESTION_WORDS = {"saltar", "saltar pregunta", "salta", "omitir", "siguiente", "paso"}
HOME_WORDS = {"vivienda", "mi vivienda", "casa", "mi casa", "hogar", "1"}
BUSINESS_WORDS = {"negocio", "mi negocio", "empresa", "pyme", "local", "tienda", "2"}
NEW_BUSINESS_WORDS = {"negocio", "otro negocio", "reportar negocio", "reportar un negocio", "empresa", "pyme"}
HOME_FROM_BUSINESS_WORDS = {"mi vivienda", "reportar mi vivienda"}
UNKNOWN_WORDS = {"no se", "nose", "no sabe", "3"}
UP_TO_DATE_WORDS = YES_WORDS | {"al dia", "si al dia", "esta al dia"}
PENDING_WORDS = NO_WORDS | {"pendiente", "no pendiente", "atrasado", "no esta al dia"}
NOT_APPLICABLE_WORDS = {"no estoy obligado", "no obligado", "no aplica", "no me aplica"}

# Orden de cada tipo de reporte entre la ubicación y la identidad: después de X sigue Y.
# WAITING_DOC_TYPE marca el paso a la identidad (que se omite si ya hay una confirmada: "otro reporte").
LOCATION_FLOW = {
    State.WAITING_ZONE: State.WAITING_ADDRESS,
    State.WAITING_ADDRESS: State.WAITING_MUNICIPALITY,
}
FLOW_NEXT: dict[str, dict[State, State]] = {
    HOME: LOCATION_FLOW
    | {
        State.WAITING_MUNICIPALITY: State.WAITING_HABITABILITY,
        State.WAITING_HABITABILITY: State.WAITING_INJURED,
        State.WAITING_INJURED: State.WAITING_SERVICES,
        State.WAITING_SERVICES: State.WAITING_URGENT_NEED,
        State.WAITING_URGENT_NEED: State.WAITING_ESTRATO,
        State.WAITING_ESTRATO: State.WAITING_HOUSEHOLD,
        State.WAITING_HOUSEHOLD: State.WAITING_VULNERABLE,
        State.WAITING_VULNERABLE: State.WAITING_ETHNICITY,
        State.WAITING_VULNERABLE_DETAIL: State.WAITING_ETHNICITY,
        State.WAITING_ETHNICITY: State.WAITING_TENURE,
        State.WAITING_TENURE: State.WAITING_DOC_TYPE,
    },
    BUSINESS: LOCATION_FLOW
    | {
        State.WAITING_MUNICIPALITY: State.WAITING_BIZ_NAME,
        State.WAITING_BIZ_NAME: State.WAITING_BIZ_ROLE,
        State.WAITING_BIZ_ROLE: State.WAITING_BIZ_PREMISES,
        State.WAITING_BIZ_PREMISES: State.WAITING_BIZ_IN_HOME,
        State.WAITING_BIZ_IN_HOME: State.WAITING_BIZ_OPERATING,
        State.WAITING_BIZ_OPERATING: State.WAITING_BIZ_STRUCTURAL_DAMAGE,
        State.WAITING_BIZ_STRUCTURAL_DAMAGE: State.WAITING_BIZ_REOPENING,  # solo si no funciona normal
        State.WAITING_BIZ_REOPENING: State.WAITING_INJURED,
        State.WAITING_INJURED: State.WAITING_SERVICES,
        State.WAITING_SERVICES: State.WAITING_BIZ_SECTOR,
        State.WAITING_BIZ_SECTOR: State.WAITING_BIZ_AGE,
        State.WAITING_BIZ_AGE: State.WAITING_BIZ_EMPLOYEES,
        State.WAITING_BIZ_EMPLOYEES: State.WAITING_BIZ_JOBS_AT_RISK,
        State.WAITING_BIZ_JOBS_AT_RISK: State.WAITING_BIZ_TENURE,
        State.WAITING_BIZ_TENURE: State.WAITING_BIZ_DIGITAL_SALES,
        State.WAITING_BIZ_DIGITAL_SALES: State.WAITING_BIZ_REGISTRY,
        # Obligaciones y finanzas: solo quien toma decisiones (BIZ_DECISION_STATES)
        State.WAITING_BIZ_REGISTRY: State.WAITING_BIZ_LEGAL_FORM,
        State.WAITING_BIZ_LEGAL_FORM: State.WAITING_BIZ_NIT,  # tipo de persona y NIT: solo si está registrado
        State.WAITING_BIZ_NIT: State.WAITING_BIZ_RUT,
        State.WAITING_BIZ_RUT: State.WAITING_BIZ_EINVOICE,
        State.WAITING_BIZ_EINVOICE: State.WAITING_BIZ_SOCIAL_SECURITY,  # solo si tiene empleados
        State.WAITING_BIZ_SOCIAL_SECURITY: State.WAITING_BIZ_ICA,
        State.WAITING_BIZ_ICA: State.WAITING_BIZ_PREDIAL,  # solo si el local es propio
        State.WAITING_BIZ_PREDIAL: State.WAITING_BIZ_SALES,
        State.WAITING_BIZ_SALES: State.WAITING_BIZ_DEBTS,
        State.WAITING_BIZ_DEBTS: State.WAITING_BIZ_PAYMENT_ACCOUNT,
        State.WAITING_BIZ_PAYMENT_ACCOUNT: State.WAITING_BIZ_LEADERSHIP,
        # Para todos
        State.WAITING_BIZ_LEADERSHIP: State.WAITING_BIZ_LOSSES,
        State.WAITING_BIZ_LOSSES: State.WAITING_BIZ_LOSS_VALUE,  # solo si perdió algo
        State.WAITING_BIZ_LOSS_VALUE: State.WAITING_BIZ_INSURANCE,
        State.WAITING_BIZ_INSURANCE: State.WAITING_BIZ_NEEDS,
        State.WAITING_BIZ_NEEDS: State.WAITING_BIZ_TOP_NEED,  # solo si marcó varias
        State.WAITING_BIZ_TOP_NEED: State.WAITING_BIZ_REP_NAME,  # representante: si quien reporta no lo es
        State.WAITING_BIZ_REP_NAME: State.WAITING_BIZ_REP_DOCUMENT,
        State.WAITING_BIZ_REP_DOCUMENT: State.WAITING_DOC_TYPE,
    },
}

BIZ_DECISION_STATES = {
    State.WAITING_BIZ_REGISTRY,
    State.WAITING_BIZ_LEGAL_FORM,
    State.WAITING_BIZ_NIT,
    State.WAITING_BIZ_RUT,
    State.WAITING_BIZ_EINVOICE,
    State.WAITING_BIZ_SOCIAL_SECURITY,
    State.WAITING_BIZ_ICA,
    State.WAITING_BIZ_PREDIAL,
    State.WAITING_BIZ_SALES,
    State.WAITING_BIZ_DEBTS,
    State.WAITING_BIZ_PAYMENT_ACCOUNT,
}

# Preguntas que se pueden saltar, con el nombre que queda en reports.skipped_questions.
# No se saltan: autorización, tipo, zona, municipio, nombre del negocio, rol de quien reporta, tipo de
# local, identidad ni fotos (sin ellas el reporte no sirve).
SKIPPABLE = {
    State.WAITING_ADDRESS: "direccion",
    State.WAITING_HABITABILITY: "habitabilidad",
    State.WAITING_INJURED: "heridos",
    State.WAITING_SERVICES: "servicios",
    State.WAITING_URGENT_NEED: "necesidad_urgente",
    State.WAITING_ESTRATO: "estrato",
    State.WAITING_HOUSEHOLD: "personas_hogar",
    State.WAITING_VULNERABLE: "poblacion_vulnerable",
    State.WAITING_VULNERABLE_DETAIL: "poblacion_vulnerable",
    State.WAITING_ETHNICITY: "pertenencia_etnica",
    State.WAITING_TENURE: "tenencia",
    State.WAITING_BIZ_IN_HOME: "negocio_en_vivienda",
    State.WAITING_BIZ_OPERATING: "funcionamiento",
    State.WAITING_BIZ_STRUCTURAL_DAMAGE: "dano_local",
    State.WAITING_BIZ_REOPENING: "reapertura",
    State.WAITING_BIZ_SECTOR: "sector",
    State.WAITING_BIZ_AGE: "antiguedad",
    State.WAITING_BIZ_EMPLOYEES: "trabajadores",
    State.WAITING_BIZ_JOBS_AT_RISK: "empleos_en_riesgo",
    State.WAITING_BIZ_TENURE: "tenencia_local",
    State.WAITING_BIZ_DIGITAL_SALES: "ventas_digitales",
    State.WAITING_BIZ_REGISTRY: "registro_mercantil",
    State.WAITING_BIZ_LEGAL_FORM: "tipo_persona",
    State.WAITING_BIZ_NIT: "nit",
    State.WAITING_BIZ_RUT: "rut",
    State.WAITING_BIZ_EINVOICE: "facturacion_electronica",
    State.WAITING_BIZ_SOCIAL_SECURITY: "seguridad_social",
    State.WAITING_BIZ_ICA: "ica",
    State.WAITING_BIZ_PREDIAL: "predial",
    State.WAITING_BIZ_SALES: "ventas_mensuales",
    State.WAITING_BIZ_DEBTS: "deudas",
    State.WAITING_BIZ_PAYMENT_ACCOUNT: "cuenta_apoyos",
    State.WAITING_BIZ_LEADERSHIP: "liderazgo",
    State.WAITING_BIZ_LOSSES: "perdidas",
    State.WAITING_BIZ_LOSS_VALUE: "valor_perdidas",
    State.WAITING_BIZ_INSURANCE: "seguro",
    State.WAITING_BIZ_NEEDS: "necesidades_negocio",
    State.WAITING_BIZ_TOP_NEED: "necesidad_principal",
    State.WAITING_BIZ_REP_NAME: "nombre_representante",
    State.WAITING_BIZ_REP_DOCUMENT: "documento_representante",
}

Options = tuple[tuple[str, str, str], ...]  # (id, título, descripción)


@dataclass(frozen=True)
class BizList:
    """Pregunta de negocio que se responde eligiendo de una lista y se guarda en un campo de Business."""

    prefix: str
    options: Options
    field: str
    body: str | Callable[[Business | None], str]  # función si el texto depende del negocio
    section: str


BIZ_LISTS = {
    State.WAITING_BIZ_ROLE: BizList(BIZ_ROLE_PREFIX, content.BIZ_ROLE_OPTIONS, "reporter_role", lambda b: content.ask_biz_role(b.name if b else None), content.BIZ_ROLE_SECTION),
    State.WAITING_BIZ_PREMISES: BizList(BIZ_PREMISES_PREFIX, content.BIZ_PREMISES_OPTIONS, "premises", content.ASK_BIZ_PREMISES, content.BIZ_PREMISES_SECTION),
    State.WAITING_BIZ_OPERATING: BizList(BIZ_OPERATING_PREFIX, content.BIZ_OPERATING_OPTIONS, "operating_status", content.ASK_BIZ_OPERATING, content.BIZ_OPERATING_SECTION),
    State.WAITING_BIZ_STRUCTURAL_DAMAGE: BizList(BIZ_DAMAGE_PREFIX, content.BIZ_STRUCTURAL_DAMAGE_OPTIONS, "structural_damage", content.ASK_BIZ_STRUCTURAL_DAMAGE, content.BIZ_STRUCTURAL_DAMAGE_SECTION),
    State.WAITING_BIZ_REOPENING: BizList(BIZ_REOPENING_PREFIX, content.BIZ_REOPENING_OPTIONS, "reopening_estimate", content.ASK_BIZ_REOPENING, content.BIZ_REOPENING_SECTION),
    State.WAITING_BIZ_SECTOR: BizList(BIZ_SECTOR_PREFIX, content.BIZ_SECTOR_OPTIONS, "sector", content.ASK_BIZ_SECTOR, content.BIZ_SECTOR_SECTION),
    State.WAITING_BIZ_AGE: BizList(BIZ_AGE_PREFIX, content.BIZ_AGE_OPTIONS, "age_range", content.ASK_BIZ_AGE, content.BIZ_AGE_SECTION),
    State.WAITING_BIZ_EMPLOYEES: BizList(BIZ_EMPLOYEES_PREFIX, content.BIZ_EMPLOYEES_OPTIONS, "employees_range", content.ASK_BIZ_EMPLOYEES, content.BIZ_EMPLOYEES_SECTION),
    State.WAITING_BIZ_TENURE: BizList(BIZ_TENURE_PREFIX, content.BIZ_TENURE_OPTIONS, "tenure", content.ASK_BIZ_TENURE, content.BIZ_TENURE_SECTION),
    State.WAITING_BIZ_REGISTRY: BizList(BIZ_REGISTRY_PREFIX, content.BIZ_REGISTRY_OPTIONS, "registry_status", content.ASK_BIZ_REGISTRY, content.BIZ_REGISTRY_SECTION),
    State.WAITING_BIZ_LEGAL_FORM: BizList(BIZ_LEGAL_FORM_PREFIX, content.BIZ_LEGAL_FORM_OPTIONS, "legal_form", content.ASK_BIZ_LEGAL_FORM, content.BIZ_LEGAL_FORM_SECTION),
    State.WAITING_BIZ_SALES: BizList(BIZ_SALES_PREFIX, content.BIZ_SALES_OPTIONS, "monthly_sales", content.ASK_BIZ_SALES, content.BIZ_SALES_SECTION),
    State.WAITING_BIZ_PAYMENT_ACCOUNT: BizList(BIZ_PAYMENT_PREFIX, content.BIZ_PAYMENT_ACCOUNT_OPTIONS, "payment_account", content.ASK_BIZ_PAYMENT_ACCOUNT, content.BIZ_PAYMENT_ACCOUNT_SECTION),
    State.WAITING_BIZ_LOSS_VALUE: BizList(BIZ_LOSS_VALUE_PREFIX, content.BIZ_LOSS_VALUE_OPTIONS, "loss_value", content.ASK_BIZ_LOSS_VALUE, content.BIZ_LOSS_VALUE_SECTION),
}


@dataclass(frozen=True)
class Obligation:
    """Obligación del negocio que se responde con botones: Sí, al día / No, pendiente / tercer botón."""

    field: str
    body: str
    not_applicable: bool = False  # el tercer botón es "No estoy obligado" en vez de "No sé"


COMPLIANCE = {
    State.WAITING_BIZ_RUT: Obligation("rut_status", content.ASK_BIZ_RUT),
    State.WAITING_BIZ_EINVOICE: Obligation("einvoice_status", content.ASK_BIZ_EINVOICE, not_applicable=True),
    State.WAITING_BIZ_SOCIAL_SECURITY: Obligation("social_security_status", content.ASK_BIZ_SOCIAL_SECURITY),
    State.WAITING_BIZ_ICA: Obligation("ica_status", content.ASK_BIZ_ICA),
    State.WAITING_BIZ_PREDIAL: Obligation("predial_status", content.ASK_BIZ_PREDIAL),
}

def numbered_options(options: tuple[tuple[str, str], ...]) -> dict[str, str]:
    """Selección múltiple por números: {"1": id1, "2": id2, ...}."""
    return {str(n): value for n, (value, _label) in enumerate(options, start=1)}


LEADERSHIP_OPTIONS = numbered_options(content.BIZ_LEADERSHIP_OPTIONS)
LOSS_OPTIONS = numbered_options(content.BIZ_LOSS_OPTIONS)
DEBT_OPTIONS = numbered_options(content.BIZ_DEBT_OPTIONS)
NEED_OPTIONS = numbered_options(tuple((value, title) for value, title, _ in content.BIZ_NEED_OPTIONS))

VULNERABLE_OPTIONS = {
    "1": VulnerableGroup.NINOS,
    "2": VulnerableGroup.ADULTOS_MAYORES,
    "3": VulnerableGroup.DISCAPACIDAD,
    "4": VulnerableGroup.EMBARAZO,
    "5": VulnerableGroup.VICTIMA_CONFLICTO,
    "6": VulnerableGroup.MIGRANTE,
    "7": VulnerableGroup.JEFATURA_FEMENINA,
    "8": VulnerableGroup.ENFERMEDAD_CRONICA,
}


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    without_punctuation = re.sub(r"[^\w\s]", " ", without_accents)  # "¡Sí, acepto!" -> "si acepto"
    return re.sub(r"\s+", " ", without_punctuation).strip()


def option_lookup(options: Options) -> dict[str, str]:
    """Respuestas escritas aceptadas para una lista: su número, su id o su título."""
    lookup: dict[str, str] = {}
    for position, (value, title, _description) in enumerate(options, start=1):
        for key in (str(position), value, title, title.replace("(a)", "")):
            lookup.setdefault(normalize(key), value)
    return lookup


class MessagingClient(Protocol):
    async def send(self, to: str, message: Outgoing) -> dict: ...
    async def mark_as_read(self, message_id: str) -> None: ...
    async def download_media(self, media_id: str) -> DownloadedMedia: ...


@dataclass
class Ctx:
    db: Session
    user: User
    msg: IncomingMessage
    out: list[Outgoing] = field(default_factory=list)

    @property
    def raw_text(self) -> str:
        return (self.msg.text or "").strip() if self.msg.kind == MessageKind.TEXT else ""

    @property
    def norm(self) -> str:
        return normalize(self.raw_text)

    def answered(self, button_id: str, words: set[str]) -> bool:
        if self.msg.kind == MessageKind.REPLY:
            return self.msg.reply_id == button_id
        return self.norm in words

    def chose(self, prefix: str, options: Options) -> str | None:
        """Id elegido de una lista, ya sea tocando la fila o escribiendo su número o nombre."""
        if self.msg.kind == MessageKind.REPLY:
            value = (self.msg.reply_id or "").removeprefix(prefix)
            return value if any(value == option[0] for option in options) else None
        return option_lookup(options).get(self.norm) if self.norm else None


Handler = Callable[[Ctx], Awaitable[None]]


class Bot:
    def __init__(
        self,
        settings: Settings,
        client: MessagingClient,
        session_factory: sessionmaker[Session],
        ocr: Callable[[Path], IdData] = ocr_service.extract_id_data,
        vision: Callable[[list[Path]], DamageAssessment] = vision_service.analyze_building_damage,
    ):
        self._settings = settings
        self._client = client
        self._session_factory = session_factory
        self._ocr = ocr
        self._vision = vision
        # Un usuario puede mandar 3 fotos a la vez: sus mensajes se procesan de uno en uno.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # OCR y visión consumen mucha RAM/CPU: como máximo 2 análisis a la vez para todo el servidor.
        self._analysis_slots = asyncio.Semaphore(MAX_CONCURRENT_ANALYSIS)
        self._handlers: dict[State, Handler] = {
            State.START: self._on_start,
            State.WAITING_TERMS: self._on_terms,
            State.WAITING_REPORT_TYPE: self._on_report_type,
            State.WAITING_AT_PROPERTY: self._on_at_property,
            State.WAITING_LOCATION: self._on_location,
            State.WAITING_ZONE: self._on_zone,
            State.WAITING_ADDRESS: self._on_address,
            State.WAITING_MUNICIPALITY: self._on_municipality,
            State.WAITING_HABITABILITY: self._on_habitability,
            State.WAITING_INJURED: self._on_injured,
            State.WAITING_SERVICES: self._on_services,
            State.WAITING_URGENT_NEED: self._on_urgent_need,
            State.WAITING_ESTRATO: self._on_estrato,
            State.WAITING_HOUSEHOLD: self._on_household,
            State.WAITING_VULNERABLE: self._on_vulnerable,
            State.WAITING_VULNERABLE_DETAIL: self._on_vulnerable_detail,
            State.WAITING_ETHNICITY: self._on_ethnicity,
            State.WAITING_TENURE: self._on_tenure,
            State.WAITING_BIZ_NAME: self._on_biz_name,
            State.WAITING_BIZ_IN_HOME: self._on_biz_in_home,
            State.WAITING_BIZ_JOBS_AT_RISK: self._on_biz_jobs_at_risk,
            State.WAITING_BIZ_NIT: self._on_biz_nit,
            State.WAITING_BIZ_LEADERSHIP: self._on_biz_leadership,
            State.WAITING_BIZ_LOSSES: self._on_biz_losses,
            State.WAITING_BIZ_INSURANCE: self._on_biz_insurance,
            State.WAITING_BIZ_DIGITAL_SALES: self._on_biz_digital_sales,
            State.WAITING_BIZ_DEBTS: self._on_biz_debts,
            State.WAITING_BIZ_NEEDS: self._on_biz_needs,
            State.WAITING_BIZ_TOP_NEED: self._on_biz_top_need,
            **{state: self._on_biz_obligation for state in COMPLIANCE},
            State.WAITING_BIZ_REP_NAME: self._on_biz_rep_name,
            State.WAITING_BIZ_REP_DOCUMENT: self._on_biz_rep_document,
            **{state: self._on_biz_list for state in BIZ_LISTS},
            State.WAITING_DOC_TYPE: self._on_doc_type,
            State.WAITING_ID_METHOD: self._on_id_method,
            State.WAITING_CEDULA: self._on_cedula,
            State.WAITING_ID_CONFIRM: self._on_id_confirm,
            State.WAITING_MANUAL_NAME: self._on_manual_name,
            State.WAITING_MANUAL_DOCUMENT: self._on_manual_document,
            State.WAITING_SELFIE_CONSENT: self._on_selfie_consent,
            State.WAITING_SELFIE: self._on_selfie,
            State.WAITING_DAMAGE_PHOTOS: self._on_damage_photos,
            State.COMPLETED: self._on_completed,
        }

    @property
    def _media_dir(self) -> Path:
        return self._settings.MEDIA_DIR

    # ------------------------------------------------------------------ entrada

    async def handle_safely(self, msg: IncomingMessage) -> None:
        try:
            await self.handle(msg)
        except Exception:
            logger.exception("Error inesperado procesando el mensaje %s", msg.wamid)

    async def handle(self, msg: IncomingMessage) -> None:
        async with self._locks[msg.from_phone]:
            with self._session_factory() as db:
                if not self._claim(db, msg.wamid):
                    logger.info("Mensaje %s ya procesado; se ignora", msg.wamid)
                    return
                user = self._get_or_create_user(db, msg)
                ctx = Ctx(db=db, user=user, msg=msg)
                try:
                    await self._dispatch(ctx)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Error procesando el mensaje %s", msg.wamid)
                    ctx.out = [Text(content.GENERIC_ERROR)]
            await self._deliver(msg, ctx.out)

    def _claim(self, db: Session, wamid: str) -> bool:
        if db.get(ProcessedMessage, wamid) is not None:
            return False
        db.add(ProcessedMessage(wamid=wamid))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return False
        return True

    def _get_or_create_user(self, db: Session, msg: IncomingMessage) -> User:
        user = db.get(User, msg.from_phone)
        if user is None:
            user = User(phone=msg.from_phone, state=State.START)
            db.add(user)
        if msg.profile_name:
            user.profile_name = msg.profile_name
        return user

    async def _deliver(self, msg: IncomingMessage, out: list[Outgoing]) -> None:
        try:
            await self._client.mark_as_read(msg.wamid)
        except MetaAPIError:
            logger.warning("No se pudo marcar como leído %s", msg.wamid)
        for message in out:
            try:
                await self._client.send(msg.from_phone, message)
            except MetaAPIError:
                logger.exception("No se pudo enviar un mensaje a %s", msg.from_phone)

    def _is_demo_phone(self, ctx: Ctx) -> bool:
        return ctx.user.phone in self._settings.demo_phones

    def _display_name(self, ctx: Ctx) -> str | None:
        # En los celulares del stand el nombre de perfil es el del dueño, no el del visitante.
        return None if self._is_demo_phone(ctx) else ctx.user.profile_name

    async def _notify_now(self, ctx: Ctx, body: str) -> None:
        """Envía un aviso inmediato (antes de un proceso lento), sin esperar al final del handler."""
        try:
            await self._client.send(ctx.user.phone, Text(body))
        except MetaAPIError:
            logger.warning("No se pudo enviar el aviso a %s", ctx.user.phone)

    async def _dispatch(self, ctx: Ctx) -> None:
        if ctx.norm in DEMO_RESET_WORDS and self._is_demo_phone(ctx):
            await self._demo_reset(ctx)
            return
        if ctx.norm in CANCEL_WORDS:
            await self._cancel(ctx)
            return
        if ctx.norm in HELP_WORDS:
            ctx.out.append(Text(content.HELP))
            return
        try:
            state = State(ctx.user.state)
        except ValueError:
            logger.warning("Estado desconocido %r; se reinicia", ctx.user.state)
            state = State.START
        if state in SKIPPABLE and (
            (ctx.msg.kind == MessageKind.REPLY and ctx.msg.reply_id == BTN_SKIP) or ctx.norm in SKIP_QUESTION_WORDS
        ):
            await self._skip_question(ctx, state)
            return
        await self._handlers[state](ctx)

    async def _skip_question(self, ctx: Ctx, state: State) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        skipped = [q for q in (report.skipped_questions or "").split(",") if q]
        if SKIPPABLE[state] not in skipped:
            skipped.append(SKIPPABLE[state])
        report.skipped_questions = ",".join(skipped)
        ctx.out.append(Text(content.SKIPPED))
        self._advance(ctx, state, report)

    def _advance(self, ctx: Ctx, current: State, report: Report) -> None:
        """Pasa a la pregunta que sigue a `current` (igual si se respondió o se saltó)."""
        flow = FLOW_NEXT[report.report_type or HOME]
        next_state = flow[current]
        while self._not_applicable(next_state, report):
            next_state = flow[next_state]
        if next_state in BIZ_DECISION_STATES and current not in BIZ_DECISION_STATES:
            ctx.out.append(Text(content.OBLIGATIONS_INTRO))
        if next_state == State.WAITING_DOC_TYPE:
            self._to_identity(ctx, report)
        else:
            self._goto(ctx, next_state, report)

    @staticmethod
    def _not_applicable(state: State, report: Report) -> bool:
        """Preguntas que no aplican según respuestas anteriores (se omiten sin quedar como saltadas)."""
        business = report.business
        match state:
            case State.WAITING_ESTRATO if report.zone == content.ZONE_RURAL:
                report.estrato = "RURAL"  # en zona rural no hay estrato: no se pregunta
                return True
            case _ if state in BIZ_DECISION_STATES and (business is None or business.reporter_role not in content.BIZ_DECISION_ROLES):
                return True  # obligaciones y finanzas: solo las responde quien toma decisiones
            case State.WAITING_BIZ_LEGAL_FORM | State.WAITING_BIZ_NIT:
                return business is None or business.registry_status not in content.BIZ_REGISTERED
            case State.WAITING_BIZ_SOCIAL_SECURITY:
                return business is None or business.employees_range == "1"  # "Solo yo": sin empleados
            case State.WAITING_BIZ_PREDIAL:
                return business is None or business.tenure != "PROPIO"  # si es arrendado, lo paga el dueño del local
            case State.WAITING_BIZ_REOPENING:
                return business is None or business.operating_status not in content.BIZ_REOPENING_ASKED_FOR
            case State.WAITING_BIZ_LOSS_VALUE:
                return business is None or business.losses in (None, content.NONE_SELECTED)
            case State.WAITING_BIZ_TOP_NEED:
                return business is None or "," not in (business.needs or "")
            case State.WAITING_BIZ_REP_NAME | State.WAITING_BIZ_REP_DOCUMENT:
                return business is None or business.reporter_is_legal_rep is not False
        return False

    # ------------------------------------------------------------------ utilidades

    def _draft(self, ctx: Ctx) -> Report | None:
        return ctx.db.scalar(
            select(Report)
            .where(Report.user_phone == ctx.user.phone, Report.status == ReportStatus.BORRADOR)
            .order_by(Report.id.desc())
        )

    def _discard_draft(self, ctx: Ctx) -> bool:
        draft = self._draft(ctx)
        if draft is None:
            return False
        media_service.delete_files(self._media_dir, list(draft.media_files))
        ctx.db.delete(draft)
        ctx.db.flush()
        return True

    def _new_draft(self, ctx: Ctx) -> Report:
        self._discard_draft(ctx)
        report = Report(user_phone=ctx.user.phone, status=ReportStatus.BORRADOR)
        ctx.db.add(report)
        ctx.db.flush()
        return report

    async def _draft_or_restart(self, ctx: Ctx) -> Report | None:
        """Devuelve el borrador en curso. Si no existe (datos inconsistentes), reencauza la conversación."""
        draft = self._draft(ctx)
        if draft is not None:
            return draft
        logger.warning("Usuario %s en %s sin borrador; se reinicia", ctx.user.phone, ctx.user.state)
        if ctx.user.terms_accepted_at is None:
            await self._on_start(ctx)
        else:
            self._goto(ctx, State.WAITING_REPORT_TYPE, self._new_draft(ctx))
        return None

    @staticmethod
    def _set_report_type(report: Report, report_type: str) -> None:
        report.report_type = report_type
        report.business = Business() if report_type == BUSINESS else None

    @staticmethod
    def _business(report: Report) -> Business:
        if report.business is None:  # no debería pasar: se crea al elegir "Mi negocio"
            report.business = Business()
        return report.business

    def _last_submitted(self, ctx: Ctx) -> Report | None:
        return ctx.db.scalar(
            select(Report)
            .where(Report.user_phone == ctx.user.phone, Report.status != ReportStatus.BORRADOR)
            .order_by(Report.id.desc())
            .limit(1)
        )

    def _pending_home(self, ctx: Ctx) -> Report | None:
        """El último reporte es de un negocio que funciona en la vivienda: se ofrece reportar la vivienda."""
        last = self._last_submitted(ctx)
        if last is not None and last.report_type == BUSINESS and last.business and last.business.in_home:
            return last
        return None

    def _has_submitted_reports(self, ctx: Ctx) -> bool:
        return (
            ctx.db.scalar(
                select(Report.id)
                .where(Report.user_phone == ctx.user.phone, Report.status != ReportStatus.BORRADOR)
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _damage_photos(report: Report) -> list[MediaFile]:
        return [m for m in report.media_files if m.kind == MediaKind.DANO]

    def _goto(self, ctx: Ctx, state: State, report: Report | None = None) -> None:
        ctx.user.state = state
        ctx.out.extend(self._prompt(ctx, state, report))

    def _invalid(self, ctx: Ctx, hint: str | None = None, report: Report | None = None) -> None:
        ctx.out.append(Text(hint or content.INVALID))
        ctx.out.extend(self._prompt(ctx, State(ctx.user.state), report))

    @staticmethod
    def _options_list(body: str, section: str, prefix: str, options: Options, skippable: bool = False) -> ListMessage:
        rows = tuple((prefix + value, title, description) for value, title, description in options)
        if skippable:
            rows += ((BTN_SKIP, content.SKIP_ROW_TITLE, content.SKIP_ROW_DESCRIPTION),)
        return ListMessage(body, content.LIST_BUTTON, section, rows)

    @staticmethod
    def _municipality_page(page: int, business: bool = False) -> ListMessage:
        """Lista de municipios paginada: WhatsApp no admite más de 10 filas por lista."""
        size = content.MUNICIPALITY_PAGE_SIZE
        if page == 1:
            options, body = content.MUNICIPALITY_OPTIONS[:size], content.ask_municipality(business)
            extra = (MUNICIPALITY_PREFIX + content.MUNICIPALITY_MORE_ID, "Ver más municipios", "Más opciones de la lista")
        else:
            options, body = content.MUNICIPALITY_OPTIONS[size:], content.ASK_MUNICIPALITY_MORE
            extra = (MUNICIPALITY_PREFIX + content.MUNICIPALITY_OTHER_ID, "Otro municipio", "Lo escribo yo")
        rows = tuple((MUNICIPALITY_PREFIX + value, title, department) for value, title, department in options)
        return ListMessage(body, content.MUNICIPALITY_BUTTON, content.MUNICIPALITY_SECTION, rows + (extra,))

    def _prompt(self, ctx: Ctx, state: State, report: Report | None) -> list[Outgoing]:
        rural = report is not None and report.zone == content.ZONE_RURAL
        business = report is not None and report.report_type == BUSINESS
        biz = report.business if report is not None else None
        if state in BIZ_LISTS:
            q = BIZ_LISTS[state]
            body = q.body(biz) if callable(q.body) else q.body
            return [self._options_list(body, q.section, q.prefix, q.options, skippable=state in SKIPPABLE)]
        if state in COMPLIANCE:
            o = COMPLIANCE[state]
            third = (BTN_NOT_APPLICABLE, "No estoy obligado") if o.not_applicable else (BTN_UNKNOWN, "No sé")
            return [Buttons(o.body, ((BTN_YES, "Sí, al día"), (BTN_NO, "No, pendiente"), third))]
        match state:
            case State.WAITING_REPORT_TYPE:
                return [Buttons(content.ASK_REPORT_TYPE, ((BTN_TYPE_HOME, "Mi vivienda"), (BTN_TYPE_BUSINESS, "Mi negocio")))]
            case State.WAITING_ZONE:
                return [Buttons(content.ask_zone(business), ((BTN_ZONE_URBAN, "Zona urbana"), (BTN_ZONE_RURAL, "Zona rural")))]
            case State.WAITING_BIZ_NAME:
                return [Text(content.ASK_BIZ_NAME)]
            case State.WAITING_BIZ_IN_HOME:
                return [Buttons(content.ASK_BIZ_IN_HOME, ((BTN_YES, "Sí"), (BTN_NO, "No"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_BIZ_JOBS_AT_RISK:
                return [Buttons(content.ASK_BIZ_JOBS_AT_RISK, ((BTN_NO, "Ninguna"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_BIZ_NIT:
                return [Text(content.ASK_BIZ_NIT)]
            case State.WAITING_BIZ_LEADERSHIP:
                return [Buttons(content.ASK_BIZ_LEADERSHIP, ((BTN_NO, "Ninguna de estas"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_BIZ_LOSSES:
                return [Buttons(content.ASK_BIZ_LOSSES, ((BTN_NO, "Nada"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_BIZ_INSURANCE:
                return [Buttons(content.ASK_BIZ_INSURANCE, ((BTN_YES, "Sí"), (BTN_NO, "No"), (BTN_UNKNOWN, "No sé")))]
            case State.WAITING_BIZ_DIGITAL_SALES:
                return [Buttons(content.ASK_BIZ_DIGITAL_SALES, ((BTN_YES, "Sí"), (BTN_NO, "No"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_BIZ_DEBTS:
                return [Buttons(content.ASK_BIZ_DEBTS, ((BTN_NO, "Ninguna"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_BIZ_NEEDS:
                return [Buttons(content.ASK_BIZ_NEEDS, ((BTN_NO, "Ninguna por ahora"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_BIZ_TOP_NEED:
                rows = tuple((BIZ_TOP_NEED_PREFIX + v, t, d) for v, t, d in self._top_need_options(biz))
                if not rows:
                    return []
                return [ListMessage(content.ASK_BIZ_TOP_NEED, content.LIST_BUTTON, content.BIZ_TOP_NEED_SECTION, rows)]
            case State.WAITING_BIZ_REP_NAME:
                return [Text(content.ASK_BIZ_REP_NAME)]
            case State.WAITING_BIZ_REP_DOCUMENT:
                return [Text(content.ASK_BIZ_REP_DOCUMENT)]
            case State.WAITING_HABITABILITY:
                return [self._options_list(content.ASK_HABITABILITY, content.HABITABILITY_SECTION, HABITABILITY_PREFIX, content.HABITABILITY_OPTIONS, skippable=True)]
            case State.WAITING_INJURED:
                return [Buttons(content.ASK_INJURED, ((BTN_YES, "Sí"), (BTN_NO, "No"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_SERVICES:
                return [self._options_list(content.ASK_SERVICES, content.SERVICES_SECTION, SERVICES_PREFIX, content.SERVICES_OPTIONS, skippable=True)]
            case State.WAITING_URGENT_NEED:
                return [self._options_list(content.ASK_URGENT_NEED, content.URGENT_NEED_SECTION, URGENT_NEED_PREFIX, content.URGENT_NEED_OPTIONS, skippable=True)]
            case State.WAITING_ESTRATO:
                return [self._options_list(content.ASK_ESTRATO, content.ESTRATO_SECTION, ESTRATO_PREFIX, content.ESTRATO_OPTIONS, skippable=True)]
            case State.WAITING_ETHNICITY:
                return [self._options_list(content.ASK_ETHNICITY, content.ETHNICITY_SECTION, ETHNICITY_PREFIX, content.ETHNICITY_OPTIONS)]
            case State.WAITING_DOC_TYPE:
                return [self._options_list(content.ASK_DOC_TYPE, content.DOC_TYPE_SECTION, DOC_TYPE_PREFIX, content.DOC_TYPE_OPTIONS)]
            case State.WAITING_ID_METHOD:
                return [Buttons(content.ASK_ID_METHOD, ((BTN_ID_PHOTO, "Sí, enviar foto"), (BTN_ID_NOPHOTO, "No la tengo")))]
            case State.WAITING_SELFIE_CONSENT:
                return [Buttons(content.ASK_SELFIE_CONSENT, ((BTN_SELFIE_YES, "Sí, autorizo"), (BTN_SELFIE_NO, "No, continuar")))]
            case State.WAITING_SELFIE:
                return [Text(content.ASK_SELFIE)]
            case State.WAITING_TERMS:
                return [Buttons(content.TERMS, ((BTN_ACCEPT, "Acepto"), (BTN_REJECT, "No acepto")))]
            case State.WAITING_AT_PROPERTY:
                return [Buttons(content.ask_at_property(business), ((BTN_YES, "Sí"), (BTN_NO, "No")))]
            case State.WAITING_LOCATION:
                at_property = report.at_property if report and report.at_property is not None else True
                return [LocationRequest(content.ask_location(at_property, business))]
            case State.WAITING_ADDRESS:
                return [Text(content.ASK_ADDRESS_RURAL if rural else content.ask_address(business))]
            case State.WAITING_MUNICIPALITY:
                if rural:
                    return [Text(content.ask_municipality_rural(business))]
                return [self._municipality_page(1, business)]
            case State.WAITING_HOUSEHOLD:
                rows = tuple((HOUSEHOLD_PREFIX + value, title, "") for value, title in content.HOUSEHOLD_OPTIONS)
                rows += ((BTN_SKIP, content.SKIP_ROW_TITLE, content.SKIP_ROW_DESCRIPTION),)
                return [ListMessage(content.ASK_HOUSEHOLD, content.HOUSEHOLD_BUTTON, content.HOUSEHOLD_SECTION, rows)]
            case State.WAITING_VULNERABLE:
                return [Buttons(content.ASK_VULNERABLE, ((BTN_YES, "Sí"), (BTN_NO, "No"), (BTN_SKIP, "Saltar")))]
            case State.WAITING_VULNERABLE_DETAIL:
                return [Text(content.ASK_VULNERABLE_DETAIL)]
            case State.WAITING_TENURE:
                return [self._options_list(content.ASK_TENURE, content.TENURE_SECTION, TENURE_PREFIX, content.TENURE_OPTIONS, skippable=True)]
            case State.WAITING_CEDULA:
                return [Text(content.ASK_CEDULA)]
            case State.WAITING_ID_CONFIRM:
                body = content.confirm_id(ctx.user.full_name or "", ctx.user.document_id or "")
                return [Buttons(body, ((BTN_ID_OK, "Sí, son correctos"), (BTN_ID_FIX, "Corregir")))]
            case State.WAITING_MANUAL_NAME:
                return [Text(content.ASK_MANUAL_NAME)]
            case State.WAITING_MANUAL_DOCUMENT:
                return [Text(content.ask_manual_document(ctx.user.document_type))]
            case State.WAITING_DAMAGE_PHOTOS:
                count = len(self._damage_photos(report)) if report else 0
                if count == 0:
                    return [Text(content.ask_damage_photos(business))]
                return [Buttons(content.photo_received(count, MAX_DAMAGE_PHOTOS), ((BTN_DONE, "Listo"),))]
            case State.COMPLETED:
                rows: tuple[tuple[str, str, str], ...] = ()
                if self._pending_home(ctx) is not None:
                    rows += ((BTN_HOME_FROM_BUSINESS, "Reportar mi vivienda", "Con la misma ubicación del negocio"),)
                if self._has_submitted_reports(ctx):
                    rows += (
                        (BTN_STATUS, "Ver mis reportes", "Código y estado de revisión"),
                        (BTN_NEW, "Reportar otra vivienda", "Otro inmueble afectado"),
                        (BTN_NEW_BUSINESS, "Reportar otro negocio", "Tienda, local, bodega o taller"),
                    )
                else:
                    rows += (
                        (BTN_NEW, "Reportar una vivienda", "Registrar daños por el sismo"),
                        (BTN_NEW_BUSINESS, "Reportar un negocio", "Tienda, local, bodega o taller"),
                    )
                rows += (
                    (BTN_COLLECTION, "Centros de acopio", "Dónde llevar o recibir ayudas"),
                    (BTN_MISSING, "Buscar desaparecidos", "Buscar o reportar a una persona"),
                    (BTN_HELP_OTHERS, "Donar o ser voluntario", "Formas de ayudar"),
                    (BTN_HUMAN, "Más ayuda", "Líneas de atención y emergencias"),
                )
                return [ListMessage(content.MENU_PROMPT, content.MENU_BUTTON, content.MENU_SECTION, rows)]
        return []

    async def _save_image(self, ctx: Ctx, report: Report, kind: MediaKind) -> MediaFile | None:
        try:
            downloaded = await self._client.download_media(ctx.msg.media_id or "")
        except MetaAPIError:
            logger.exception("No se pudo descargar la imagen %s", ctx.msg.media_id)
            ctx.out.append(Text(content.MEDIA_ERROR))
            return None
        return media_service.store_media(
            ctx.db,
            self._media_dir,
            report=report,
            kind=kind,
            content=downloaded.content,
            mime=downloaded.mime_type or ctx.msg.mime_type,
            meta_media_id=ctx.msg.media_id,
        )

    # ------------------------------------------------------------------ comandos globales

    async def _demo_reset(self, ctx: Ctx) -> None:
        """Deja un celular del stand como nuevo. Los reportes ya enviados se conservan (alimentan el mapa)."""
        self._discard_draft(ctx)
        user = ctx.user
        user.state = State.START
        user.terms_accepted_at = None
        user.full_name = user.document_id = user.document_type = user.id_source = None
        user.selfie_consent_at = None
        user.id_confirmed = False
        user.ocr_attempts = 0
        ctx.out.append(Text(content.DEMO_RESET))
        await self._on_start(ctx)

    async def _cancel(self, ctx: Ctx) -> None:
        self._discard_draft(ctx)
        ctx.out.append(Text(content.CANCELLED))
        if ctx.user.terms_accepted_at is not None:
            self._goto(ctx, State.COMPLETED)
        else:
            ctx.user.state = State.START

    # ------------------------------------------------------------------ handlers por estado

    async def _on_start(self, ctx: Ctx) -> None:
        if ctx.user.terms_accepted_at is not None:
            ctx.out.append(Text(content.welcome_back(self._display_name(ctx))))
            self._goto(ctx, State.COMPLETED)
        else:
            ctx.out.append(Text(content.welcome(self._display_name(ctx))))
            self._goto(ctx, State.WAITING_TERMS)

    async def _on_terms(self, ctx: Ctx) -> None:
        if ctx.answered(BTN_ACCEPT, ACCEPT_WORDS):
            ctx.user.terms_accepted_at = datetime.now(UTC)
            report = self._new_draft(ctx)
            ctx.out.append(Text(content.TERMS_ACCEPTED))
            self._goto(ctx, State.WAITING_REPORT_TYPE, report)
        elif ctx.answered(BTN_REJECT, REJECT_WORDS):
            ctx.out.append(Text(content.TERMS_REJECTED))
            ctx.user.state = State.START
        else:
            self._invalid(ctx)

    async def _on_report_type(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_TYPE_HOME, HOME_WORDS):
            self._set_report_type(report, HOME)
            ctx.out.append(Text(content.START_HOME))
        elif ctx.answered(BTN_TYPE_BUSINESS, BUSINESS_WORDS):
            self._set_report_type(report, BUSINESS)
            ctx.out.append(Text(content.START_BUSINESS))
        else:
            self._invalid(ctx, report=report)
            return
        self._goto(ctx, State.WAITING_AT_PROPERTY, report)

    async def _on_at_property(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_YES, YES_WORDS):
            report.at_property = True
        elif ctx.answered(BTN_NO, NO_WORDS):
            report.at_property = False
        else:
            self._invalid(ctx, report=report)
            return
        self._goto(ctx, State.WAITING_LOCATION, report)

    async def _on_location(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        msg = ctx.msg
        if (
            msg.kind == MessageKind.LOCATION
            and msg.latitude is not None
            and msg.longitude is not None
            and -90 <= msg.latitude <= 90
            and -180 <= msg.longitude <= 180
        ):
            report.latitude, report.longitude = msg.latitude, msg.longitude
        elif ctx.norm in SKIP_WORDS:
            alerts.add_alert(report, AlertCode.SIN_GPS, "El ciudadano no compartió la ubicación GPS.")
            ctx.out.append(Text(content.LOCATION_SKIPPED))
        else:
            self._invalid(ctx, content.LOCATION_INVALID, report)
            return
        self._goto(ctx, State.WAITING_ZONE, report)

    async def _on_zone(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_ZONE_URBAN, URBAN_WORDS):
            report.zone = content.ZONE_URBAN
        elif ctx.answered(BTN_ZONE_RURAL, RURAL_WORDS):
            report.zone = content.ZONE_RURAL
        else:
            self._invalid(ctx, report=report)
            return
        self._advance(ctx, State.WAITING_ZONE, report)

    async def _on_address(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if len(ctx.raw_text) < 5:
            self._invalid(ctx, report=report)
            return
        report.address_text = ctx.raw_text
        self._advance(ctx, State.WAITING_ADDRESS, report)

    async def _on_municipality(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.msg.kind == MessageKind.REPLY and report.zone != content.ZONE_RURAL:
            chosen = (ctx.msg.reply_id or "").removeprefix(MUNICIPALITY_PREFIX)
            if chosen == content.MUNICIPALITY_MORE_ID:
                ctx.out.append(self._municipality_page(2))  # sigue en el mismo estado
                return
            if chosen == content.MUNICIPALITY_OTHER_ID:
                ctx.out.append(Text(content.ASK_MUNICIPALITY_TEXT))  # sigue en el mismo estado, ahora escribe
                return
            match = next((o for o in content.MUNICIPALITY_OPTIONS if o[0] == chosen), None)
            if match is None:
                self._invalid(ctx, report=report)
                return
            report.municipality = f"{match[1]}, {match[2]}"
        elif len(ctx.raw_text) >= 3:
            report.municipality = ctx.raw_text  # escrito: "otro municipio" o pueblo más cercano (rural)
        else:
            self._invalid(ctx, report=report)
            return
        self._advance(ctx, State.WAITING_MUNICIPALITY, report)

    async def _choose_into(
        self, ctx: Ctx, prefix: str, options: Options, field_name: str, on_business: bool = False
    ) -> str | None:
        """Paso genérico de lista: guarda la opción elegida (en el reporte o en su negocio) y avanza."""
        report = await self._draft_or_restart(ctx)
        if report is None:
            return None
        value = ctx.chose(prefix, options)
        if value is None:
            self._invalid(ctx, report=report)
            return None
        setattr(self._business(report) if on_business else report, field_name, value)
        title = next(t for v, t, _ in options if v == value)
        self._after_choice(ctx, report, field_name if not on_business else f"business.{field_name}", value, title)
        self._advance(ctx, State(ctx.user.state), report)
        return value

    @staticmethod
    def _after_choice(ctx: Ctx, report: Report, field_name: str, value: str, title: str) -> None:
        """Efectos de una opción elegida: datos derivados, avisos y alertas (ninguna bloquea el reporte)."""
        match field_name:
            case "business.reporter_role":
                report.business.reporter_is_legal_rep = value in content.BIZ_LEGAL_REP_ROLES
            case "business.structural_damage" if value in content.BIZ_SEVERE_DAMAGE:
                ctx.out.append(Text(content.STRUCTURAL_WARNING))
                if report.business.operating_status in ("NORMAL", "PARCIAL"):
                    alerts.add_alert(
                        report,
                        AlertCode.RIESGO_ESTRUCTURAL,
                        f"El negocio sigue funcionando con el local en estado: {title}.",
                    )
            case "habitability" if value.startswith(content.DISPLACED_PREFIX):
                alerts.add_alert(report, AlertCode.SIN_VIVIENDA, f"El hogar no puede habitar la vivienda ({title}).")
            case "business.operating_status" if value.startswith(content.BIZ_CLOSED_PREFIX):
                alerts.add_alert(report, AlertCode.NEGOCIO_CERRADO, f"El negocio no puede funcionar ({title}).")
            case "business.registry_status" if value == content.BIZ_INFORMAL:
                alerts.add_alert(report, AlertCode.NEGOCIO_INFORMAL, "El negocio no está registrado en la Cámara de Comercio.")
                ctx.out.append(Text(content.BIZ_INFORMAL_NOTE))
            case "business.loss_value" if value in content.BIZ_HIGH_LOSS:
                alerts.add_alert(report, AlertCode.PERDIDA_ALTA, f"Pérdidas estimadas: {title}.")

    # --- Situación de emergencia

    async def _on_habitability(self, ctx: Ctx) -> None:
        await self._choose_into(ctx, HABITABILITY_PREFIX, content.HABITABILITY_OPTIONS, "habitability")

    async def _on_injured(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_YES, YES_WORDS):
            report.injured = True
            alerts.add_alert(report, AlertCode.HERIDOS, "El ciudadano reporta personas heridas o que necesitan atención médica.")
            ctx.out.append(Text(content.INJURED_WARNING))
        elif ctx.answered(BTN_NO, NO_WORDS):
            report.injured = False
        else:
            self._invalid(ctx, report=report)
            return
        self._advance(ctx, State.WAITING_INJURED, report)

    async def _on_services(self, ctx: Ctx) -> None:
        await self._choose_into(ctx, SERVICES_PREFIX, content.SERVICES_OPTIONS, "services")

    async def _on_urgent_need(self, ctx: Ctx) -> None:
        await self._choose_into(ctx, URGENT_NEED_PREFIX, content.URGENT_NEED_OPTIONS, "urgent_need")

    # --- Hogar

    async def _on_estrato(self, ctx: Ctx) -> None:
        await self._choose_into(ctx, ESTRATO_PREFIX, content.ESTRATO_OPTIONS, "estrato")

    async def _on_ethnicity(self, ctx: Ctx) -> None:
        await self._choose_into(ctx, ETHNICITY_PREFIX, content.ETHNICITY_OPTIONS, "ethnicity")

    async def _on_household(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.msg.kind == MessageKind.REPLY:
            chosen = (ctx.msg.reply_id or "").removeprefix(HOUSEHOLD_PREFIX)
            if chosen == content.HOUSEHOLD_MORE_ID:
                ctx.out.append(Text(content.ASK_HOUSEHOLD_NUMBER))  # sigue en el mismo estado, ahora escribe
                return
            size = int(chosen) if chosen.isdigit() else 0
        else:
            numbers = re.findall(r"\d+", ctx.raw_text)
            size = int(numbers[0]) if len(numbers) == 1 else 0
        if not 1 <= size <= 30:
            self._invalid(ctx, content.INVALID_HOUSEHOLD, report)
            return
        report.household_size = size
        self._advance(ctx, State.WAITING_HOUSEHOLD, report)

    @staticmethod
    def _parse_multi(text: str, options: dict[str, str]) -> str | None:
        """Selección múltiple por números: '1,3' -> 'NINOS,DISCAPACIDAD'. None si no es una lista válida."""
        numbers = re.findall(r"\d+", text)
        if not numbers or any(n not in options for n in numbers):
            return None
        return ",".join(dict.fromkeys(options[n] for n in numbers))  # sin repetidos, en orden

    @classmethod
    def _parse_vulnerable(cls, text: str) -> str | None:
        return cls._parse_multi(text, VULNERABLE_OPTIONS)

    async def _on_vulnerable(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        # Atajo: si escribe directamente los números ("1,3"), se aceptan sin pasar por Sí.
        direct = self._parse_vulnerable(ctx.raw_text) if ctx.msg.kind == MessageKind.TEXT else None
        if direct:
            report.vulnerable_groups = direct
            self._advance(ctx, State.WAITING_VULNERABLE, report)
        elif ctx.answered(BTN_NO, NONE_WORDS):
            report.vulnerable_groups = "NINGUNO"
            self._advance(ctx, State.WAITING_VULNERABLE, report)
        elif ctx.answered(BTN_YES, YES_WORDS):
            self._goto(ctx, State.WAITING_VULNERABLE_DETAIL, report)
        else:
            self._invalid(ctx, report=report)

    async def _on_vulnerable_detail(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        groups = self._parse_vulnerable(ctx.raw_text)
        if groups is None:
            self._invalid(ctx, report=report)
            return
        report.vulnerable_groups = groups
        self._advance(ctx, State.WAITING_VULNERABLE_DETAIL, report)

    async def _on_tenure(self, ctx: Ctx) -> None:
        await self._choose_into(ctx, TENURE_PREFIX, content.TENURE_OPTIONS, "tenure")

    # --- Negocio

    async def _on_biz_list(self, ctx: Ctx) -> None:
        q = BIZ_LISTS[State(ctx.user.state)]
        await self._choose_into(ctx, q.prefix, q.options, q.field, on_business=True)

    async def _on_biz_name(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        name = " ".join(ctx.raw_text.split())
        if len(name) < 2 or ctx.norm in SKIP_QUESTION_WORDS:
            self._invalid(ctx, content.INVALID_BIZ_NAME, report)
            return
        self._business(report).name = name[:255]
        self._advance(ctx, State.WAITING_BIZ_NAME, report)

    async def _on_biz_in_home(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_YES, YES_WORDS):
            self._business(report).in_home = True
        elif ctx.answered(BTN_NO, NO_WORDS):
            self._business(report).in_home = False
        else:
            self._invalid(ctx, report=report)
            return
        self._advance(ctx, State.WAITING_BIZ_IN_HOME, report)

    async def _on_biz_jobs_at_risk(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        numbers = re.findall(r"\d+", ctx.raw_text)
        if ctx.answered(BTN_NO, NONE_WORDS):
            jobs = 0
        elif len(numbers) == 1 and int(numbers[0]) <= 100_000:
            jobs = int(numbers[0])
        else:
            self._invalid(ctx, content.INVALID_JOBS, report)
            return
        self._business(report).jobs_at_risk = jobs
        self._advance(ctx, State.WAITING_BIZ_JOBS_AT_RISK, report)

    async def _on_biz_nit(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        nit = re.sub(r"[\s.\-]", "", ctx.raw_text)
        if not re.fullmatch(r"\d{5,15}", nit):
            self._invalid(ctx, content.INVALID_NIT, report)
            return
        self._business(report).nit = nit
        self._advance(ctx, State.WAITING_BIZ_NIT, report)

    async def _multi_into(self, ctx: Ctx, options: dict[str, str], field_name: str) -> None:
        """Selección múltiple del negocio: números separados por coma, o "ninguno"."""
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        chosen = self._parse_multi(ctx.raw_text, options) if ctx.msg.kind == MessageKind.TEXT else None
        if chosen is None and ctx.answered(BTN_NO, NONE_WORDS | {"nada", "ninguna por ahora"}):
            chosen = content.NONE_SELECTED
        if chosen is None:
            self._invalid(ctx, report=report)
            return
        business = self._business(report)
        setattr(business, field_name, chosen)
        selected = chosen.split(",")
        if field_name == "debts" and content.BIZ_INFORMAL_LENDER in selected:
            alerts.add_alert(report, AlertCode.PRESTAMO_INFORMAL, "El negocio tiene deudas con un prestamista informal (gota a gota).")
        if field_name == "needs":  # con una sola necesidad, esa es la más urgente
            business.urgent_need = chosen if len(selected) == 1 and chosen != content.NONE_SELECTED else None
        self._advance(ctx, State(ctx.user.state), report)

    async def _on_biz_leadership(self, ctx: Ctx) -> None:
        await self._multi_into(ctx, LEADERSHIP_OPTIONS, "leadership_groups")

    async def _on_biz_losses(self, ctx: Ctx) -> None:
        await self._multi_into(ctx, LOSS_OPTIONS, "losses")

    async def _on_biz_insurance(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_YES, YES_WORDS):
            value = "SI"
        elif ctx.answered(BTN_NO, NO_WORDS):
            value = "NO"
        elif ctx.answered(BTN_UNKNOWN, UNKNOWN_WORDS):
            value = "NO_SABE"
        else:
            self._invalid(ctx, report=report)
            return
        self._business(report).insurance = value
        self._advance(ctx, State.WAITING_BIZ_INSURANCE, report)

    async def _on_biz_digital_sales(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_YES, YES_WORDS):
            self._business(report).digital_sales = True
        elif ctx.answered(BTN_NO, NO_WORDS):
            self._business(report).digital_sales = False
        else:
            self._invalid(ctx, report=report)
            return
        self._advance(ctx, State.WAITING_BIZ_DIGITAL_SALES, report)

    async def _on_biz_obligation(self, ctx: Ctx) -> None:
        """RUT, facturación, seguridad social, ICA y predial: ¿al día, pendiente o no sé / no aplica?"""
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        state = State(ctx.user.state)
        obligation = COMPLIANCE[state]
        unknown_words = UNKNOWN_WORDS - {"3"} if obligation.not_applicable else UNKNOWN_WORDS
        if ctx.answered(BTN_YES, UP_TO_DATE_WORDS):
            value = content.STATUS_UP_TO_DATE
        elif ctx.answered(BTN_NO, PENDING_WORDS):
            value = content.STATUS_PENDING
        elif obligation.not_applicable and ctx.answered(BTN_NOT_APPLICABLE, NOT_APPLICABLE_WORDS | {"3"}):
            value = content.STATUS_NOT_APPLICABLE
        elif ctx.answered(BTN_UNKNOWN, unknown_words):
            value = content.STATUS_UNKNOWN
        else:
            self._invalid(ctx, report=report)
            return
        setattr(self._business(report), obligation.field, value)
        self._advance(ctx, state, report)

    async def _on_biz_debts(self, ctx: Ctx) -> None:
        await self._multi_into(ctx, DEBT_OPTIONS, "debts")

    async def _on_biz_needs(self, ctx: Ctx) -> None:
        await self._multi_into(ctx, NEED_OPTIONS, "needs")

    @staticmethod
    def _top_need_options(business: Business | None) -> Options:
        """Solo las necesidades que marcó, para elegir la más urgente."""
        chosen = set((business.needs or "").split(",")) if business else set()
        return tuple((value, title, "") for value, title, _ in content.BIZ_NEED_OPTIONS if value in chosen)

    async def _on_biz_top_need(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        business = self._business(report)
        value = ctx.chose(BIZ_TOP_NEED_PREFIX, self._top_need_options(business))
        if value is None:
            self._invalid(ctx, report=report)
            return
        business.urgent_need = value
        self._advance(ctx, State.WAITING_BIZ_TOP_NEED, report)

    async def _on_biz_rep_name(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        name = " ".join(ctx.raw_text.split()).upper()
        if len(name) < 5 or len(name.split()) < 2 or any(ch.isdigit() for ch in name):
            self._invalid(ctx, content.INVALID_NAME, report)
            return
        self._business(report).legal_rep_name = name[:255]
        self._advance(ctx, State.WAITING_BIZ_REP_NAME, report)

    async def _on_biz_rep_document(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        document = re.sub(r"[\s.\-]", "", ctx.raw_text).upper()
        if not re.fullmatch(r"[A-Z0-9]{5,12}", document):
            self._invalid(ctx, content.INVALID_REP_DOCUMENT, report)
            return
        self._business(report).legal_rep_document = document
        self._advance(ctx, State.WAITING_BIZ_REP_DOCUMENT, report)

    # --- Paso a la identidad (fin del bloque de hogar o de negocio)

    def _to_identity(self, ctx: Ctx, report: Report) -> None:
        """Identidad de quien reporta, o se reutiliza la ya registrada en un reporte anterior."""
        user = ctx.user
        if user.id_confirmed and (user.document_id or user.document_type == content.DOC_NONE):
            # Otro reporte desde el mismo celular: la identidad ya está registrada y confirmada.
            if user.document_type == content.DOC_NONE:
                alerts.add_alert(report, AlertCode.SIN_DOCUMENTO, "El ciudadano declaró no tener documento de identidad.")
            ctx.out.append(Text(content.CEDULA_REUSED))
            self._goto(ctx, State.WAITING_DAMAGE_PHOTOS, report)
            return
        if report.business is not None and report.business.reporter_is_legal_rep is False:
            ctx.out.append(Text(content.ASK_REPORTER_IDENTITY))
        self._goto(ctx, State.WAITING_DOC_TYPE, report)

    # --- Identidad

    async def _on_doc_type(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        doc_type = ctx.chose(DOC_TYPE_PREFIX, content.DOC_TYPE_OPTIONS)
        if doc_type is None:
            self._invalid(ctx, report=report)
            return
        user = ctx.user
        user.document_type = doc_type
        user.full_name = user.document_id = user.id_source = None
        user.id_confirmed = False
        user.ocr_attempts = 0
        # Solo la cédula de ciudadanía pasa por foto + OCR; los demás documentos se escriben.
        self._goto(ctx, State.WAITING_ID_METHOD if doc_type == content.DOC_CC else State.WAITING_MANUAL_NAME, report)

    async def _on_id_method(self, ctx: Ctx) -> None:
        if ctx.msg.is_image:  # mandó la foto directamente: se procesa como cédula
            await self._on_cedula(ctx)
            return
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_ID_PHOTO, PHOTO_WORDS):
            self._goto(ctx, State.WAITING_CEDULA, report)
        elif ctx.answered(BTN_ID_NOPHOTO, NO_PHOTO_WORDS):
            self._goto(ctx, State.WAITING_MANUAL_NAME, report)
        else:
            self._invalid(ctx, report=report)

    def _after_identity(self, ctx: Ctx, report: Report) -> None:
        """Con la identidad lista: si no hubo foto de la cédula, se ofrece la selfie opcional."""
        sent_document_photo = any(m.kind == MediaKind.CEDULA for m in report.media_files)
        if sent_document_photo:
            self._goto(ctx, State.WAITING_DAMAGE_PHOTOS, report)
        else:
            self._goto(ctx, State.WAITING_SELFIE_CONSENT, report)

    async def _on_selfie_consent(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_SELFIE_YES, SELFIE_YES_WORDS):
            ctx.user.selfie_consent_at = datetime.now(UTC)
            self._goto(ctx, State.WAITING_SELFIE, report)
        elif ctx.answered(BTN_SELFIE_NO, SELFIE_NO_WORDS):
            ctx.out.append(Text(content.SELFIE_SKIPPED))
            self._goto(ctx, State.WAITING_DAMAGE_PHOTOS, report)
        else:
            self._invalid(ctx, report=report)

    async def _on_selfie(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.msg.is_image:
            if await self._save_image(ctx, report, MediaKind.SELFIE) is None:
                return
            ctx.out.append(Text(content.SELFIE_RECEIVED))
        elif ctx.norm in SKIP_WORDS | NO_WORDS:
            ctx.out.append(Text(content.SELFIE_SKIPPED))
        else:
            hint = content.MEDIA_NOT_IMAGE if ctx.msg.kind == MessageKind.DOCUMENT else None
            self._invalid(ctx, hint, report)
            return
        self._goto(ctx, State.WAITING_DAMAGE_PHOTOS, report)

    async def _on_cedula(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if not ctx.msg.is_image:
            hint = content.MEDIA_NOT_IMAGE if ctx.msg.kind == MessageKind.DOCUMENT else None
            self._invalid(ctx, hint, report)
            return

        media = await self._save_image(ctx, report, MediaKind.CEDULA)
        if media is None:
            return

        await self._notify_now(ctx, content.READING_CEDULA)
        try:
            async with self._analysis_slots:
                data = await asyncio.to_thread(self._ocr, media_service.absolute_path(self._media_dir, media))
        except Exception:
            logger.exception("El servicio de OCR falló")
            data = IdData(full_name=None, document_id=None)

        document_id = re.sub(r"\D", "", data.document_id or "")
        if data.is_complete and document_id:
            ctx.user.full_name = " ".join((data.full_name or "").split()).upper()
            ctx.user.document_id = document_id
            ctx.user.id_source = IdSource.OCR
            ctx.user.id_confirmed = False
            self._goto(ctx, State.WAITING_ID_CONFIRM, report)
            return

        ctx.user.ocr_attempts += 1
        if ctx.user.ocr_attempts < MAX_OCR_ATTEMPTS:
            ctx.out.append(Text(content.OCR_RETRY))
        else:
            alerts.add_alert(report, AlertCode.OCR_ILEGIBLE, f"OCR sin resultado tras {ctx.user.ocr_attempts} fotos.")
            ctx.out.append(Text(content.OCR_FAILED_MANUAL))
            self._goto(ctx, State.WAITING_MANUAL_NAME, report)

    async def _on_id_confirm(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.answered(BTN_ID_OK, YES_WORDS):
            ctx.user.id_confirmed = True
            self._after_identity(ctx, report)
        elif ctx.answered(BTN_ID_FIX, FIX_WORDS):
            alerts.add_alert(
                report,
                AlertCode.DATOS_CORREGIDOS,
                f"El OCR leyó {ctx.user.full_name} / {ctx.user.document_id}; el ciudadano lo corrigió.",
            )
            self._goto(ctx, State.WAITING_MANUAL_NAME, report)
        else:
            self._invalid(ctx, report=report)

    async def _on_manual_name(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        name = " ".join(ctx.raw_text.split()).upper()
        if len(name) < 5 or len(name.split()) < 2 or any(ch.isdigit() for ch in name):
            self._invalid(ctx, content.INVALID_NAME, report)
            return
        ctx.user.full_name = name
        if ctx.user.document_type == content.DOC_NONE:
            ctx.user.document_id = None
            ctx.user.id_source = IdSource.MANUAL
            ctx.user.id_confirmed = True
            alerts.add_alert(report, AlertCode.SIN_DOCUMENTO, "El ciudadano declaró no tener documento de identidad.")
            self._after_identity(ctx, report)
        else:
            self._goto(ctx, State.WAITING_MANUAL_DOCUMENT, report)

    async def _on_manual_document(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        document_id = re.sub(r"[\s.\-]", "", ctx.raw_text).upper()
        if ctx.user.document_type == content.DOC_PASSPORT:
            valid, hint = re.fullmatch(r"[A-Z0-9]{5,12}", document_id), content.INVALID_PASSPORT
        else:
            valid, hint = re.fullmatch(r"\d{5,12}", document_id), content.INVALID_DOCUMENT
        if not valid:
            self._invalid(ctx, hint, report)
            return
        ctx.user.document_id = document_id
        ctx.user.id_source = IdSource.MANUAL
        ctx.user.id_confirmed = True
        self._after_identity(ctx, report)

    async def _on_damage_photos(self, ctx: Ctx) -> None:
        report = await self._draft_or_restart(ctx)
        if report is None:
            return
        if ctx.msg.is_image:
            if await self._save_image(ctx, report, MediaKind.DANO) is None:
                return
            count = len(self._damage_photos(report))
            if count >= MAX_DAMAGE_PHOTOS:
                await self._submit(ctx, report)
            else:
                ctx.out.extend(self._prompt(ctx, State.WAITING_DAMAGE_PHOTOS, report))
        elif ctx.answered(BTN_DONE, DONE_WORDS):
            if not self._damage_photos(report):
                self._invalid(ctx, content.ASK_PHOTO_FIRST, report)
                return
            await self._submit(ctx, report)
        else:
            hint = content.MEDIA_NOT_IMAGE if ctx.msg.kind == MessageKind.DOCUMENT else None
            self._invalid(ctx, hint, report)

    async def _submit(self, ctx: Ctx, report: Report) -> None:
        paths = [media_service.absolute_path(self._media_dir, m) for m in self._damage_photos(report)]
        await self._notify_now(ctx, content.ANALYZING_PHOTOS)
        try:
            async with self._analysis_slots:
                assessment = await asyncio.to_thread(self._vision, paths)
        except Exception:
            logger.exception("El servicio de visión falló")
            assessment = DamageAssessment(level=None, confidence=None)

        report.damage_level = assessment.level.value if assessment.level else None
        report.damage_confidence = assessment.confidence
        report.citizen_name = ctx.user.full_name
        report.citizen_document_type = ctx.user.document_type or content.DOC_CC
        report.citizen_document_id = ctx.user.document_id
        business = report.business
        if business is not None and business.reporter_is_legal_rep:
            business.legal_rep_name = ctx.user.full_name
            business.legal_rep_document = ctx.user.document_id
        report.confirmation_code = codes.unique_confirmation_code(ctx.db)
        report.status = ReportStatus.PENDIENTE_REVISION
        report.submitted_at = datetime.now(UTC)
        ctx.db.flush()
        alerts.evaluate_on_submit(ctx.db, report)

        # El ciudadano ve el nivel estimado con sus advertencias de seguridad, antes del código.
        ctx.out.append(Text(content.damage_result(report.damage_level)))
        home_pending = business is not None and bool(business.in_home)
        ctx.out.append(Text(content.submitted(report.confirmation_code, business is not None, home_pending)))
        self._goto(ctx, State.COMPLETED)

    def _home_from_business(self, ctx: Ctx, source: Report) -> None:
        """Reporte de la vivienda donde funciona el negocio: copia la ubicación y sigue con la situación."""
        report = self._new_draft(ctx)
        for name in ("at_property", "latitude", "longitude", "zone", "address_text", "municipality"):
            setattr(report, name, getattr(source, name))
        if report.latitude is None:
            alerts.add_alert(report, AlertCode.SIN_GPS, "El ciudadano no compartió la ubicación GPS.")
        if report.address_text is None:
            report.skipped_questions = SKIPPABLE[State.WAITING_ADDRESS]
        ctx.out.append(Text(content.HOME_FROM_BUSINESS))
        self._advance(ctx, State.WAITING_MUNICIPALITY, report)

    async def _on_completed(self, ctx: Ctx) -> None:
        if ctx.answered(BTN_STATUS, STATUS_WORDS):
            reports = ctx.db.scalars(
                select(Report)
                .where(Report.user_phone == ctx.user.phone, Report.status != ReportStatus.BORRADOR)
                .order_by(Report.id.desc())
                .limit(5)
            ).all()
            if not reports:
                ctx.out.append(Text(content.NO_REPORTS))
            else:
                lines = [
                    f"• *{r.confirmation_code}*: {content.STATUS_LABELS.get(r.status, r.status)}"
                    + (f" (enviado el {r.submitted_at:%d/%m/%Y})" if r.submitted_at else "")
                    for r in reports
                ]
                ctx.out.append(Text(content.status_summary(lines)))
        elif ctx.answered(BTN_HOME_FROM_BUSINESS, HOME_FROM_BUSINESS_WORDS) and (source := self._pending_home(ctx)):
            self._home_from_business(ctx, source)
        elif ctx.answered(BTN_NEW_BUSINESS, NEW_BUSINESS_WORDS):
            report = self._new_draft(ctx)
            self._set_report_type(report, BUSINESS)
            ctx.out.append(Text(content.NEW_BUSINESS_REPORT))
            self._goto(ctx, State.WAITING_AT_PROPERTY, report)
        elif ctx.answered(BTN_NEW, NEW_WORDS):
            report = self._new_draft(ctx)
            ctx.out.append(Text(content.NEW_REPORT))
            self._goto(ctx, State.WAITING_AT_PROPERTY, report)
        elif ctx.answered(BTN_HUMAN, HUMAN_WORDS):
            ctx.out.append(Text(content.SUPPORT, preview_url=True))
        elif ctx.answered(BTN_COLLECTION, {"acopio", "centros de acopio"}):
            ctx.out.append(Text(content.LINK_COLLECTION_CENTERS, preview_url=True))
        elif ctx.answered(BTN_MISSING, {"desaparecidos", "buscar desaparecidos"}):
            ctx.out.append(Text(content.LINK_MISSING, preview_url=True))
        elif ctx.answered(BTN_HELP_OTHERS, {"donar", "voluntario", "ayudar"}):
            ctx.out.append(Text(content.LINK_HELP_OTHERS, preview_url=True))
        else:
            self._goto(ctx, State.COMPLETED)
