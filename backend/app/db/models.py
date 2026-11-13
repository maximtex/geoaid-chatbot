from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ReportStatus(StrEnum):
    BORRADOR = "BORRADOR"  # el ciudadano aún está diligenciando el reporte
    PENDIENTE_REVISION = "PENDIENTE_REVISION"
    # Reservados para el equipo revisor (aún no hay interfaz que los asigne):
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"
    REQUIERE_INFO = "REQUIERE_INFO"


class ReportType(StrEnum):
    VIVIENDA = "VIVIENDA"  # vivienda familiar
    NEGOCIO = "NEGOCIO"  # pyme o negocio (datos propios en la tabla businesses)


class DamageLevel(StrEnum):
    VERDE = "VERDE"
    AMARILLO = "AMARILLO"
    ROJO = "ROJO"


class Tenure(StrEnum):
    PROPIETARIO = "PROPIETARIO"
    ARRENDATARIO = "ARRENDATARIO"
    POSEEDOR = "POSEEDOR"
    FAMILIAR = "FAMILIAR"
    OTRO = "OTRO"


class VulnerableGroup(StrEnum):
    NINOS = "NINOS"
    ADULTOS_MAYORES = "ADULTOS_MAYORES"
    DISCAPACIDAD = "DISCAPACIDAD"
    EMBARAZO = "EMBARAZO"
    VICTIMA_CONFLICTO = "VICTIMA_CONFLICTO"
    MIGRANTE = "MIGRANTE"
    JEFATURA_FEMENINA = "JEFATURA_FEMENINA"
    ENFERMEDAD_CRONICA = "ENFERMEDAD_CRONICA"


class IdSource(StrEnum):
    OCR = "OCR"
    MANUAL = "MANUAL"


class MediaKind(StrEnum):
    CEDULA = "CEDULA"
    DANO = "DANO"
    SELFIE = "SELFIE"  # dato biométrico: solo con autorización explícita


class AlertCode(StrEnum):
    CEDULA_DUPLICADA = "CEDULA_DUPLICADA"
    TELEFONO_VARIAS_CEDULAS = "TELEFONO_VARIAS_CEDULAS"
    OCR_ILEGIBLE = "OCR_ILEGIBLE"
    DATOS_CORREGIDOS = "DATOS_CORREGIDOS"
    FOTO_REPETIDA = "FOTO_REPETIDA"
    SIN_GPS = "SIN_GPS"
    GPS_FUERA_DE_VIVIENDA = "GPS_FUERA_DE_VIVIENDA"
    HERIDOS = "HERIDOS"  # prioridad: hay personas heridas
    SIN_VIVIENDA = "SIN_VIVIENDA"  # el hogar no puede habitar la vivienda
    SIN_DOCUMENTO = "SIN_DOCUMENTO"
    # Negocios
    NEGOCIO_CERRADO = "NEGOCIO_CERRADO"
    NEGOCIO_INFORMAL = "NEGOCIO_INFORMAL"  # sin registro en Cámara de Comercio: no bloquea, se registra igual
    PERDIDA_ALTA = "PERDIDA_ALTA"  # pérdidas estimadas de 50 millones o más
    NIT_DUPLICADO = "NIT_DUPLICADO"  # el mismo NIT reportado desde otro teléfono
    RIESGO_ESTRUCTURAL = "RIESGO_ESTRUCTURAL"  # daño grave o colapso, pero el negocio sigue funcionando
    PRESTAMO_INFORMAL = "PRESTAMO_INFORMAL"  # deudas con prestamistas informales ("gota a gota")
    OBLIGACIONES_PENDIENTES = "OBLIGACIONES_PENDIENTES"  # registro, RUT, ICA, etc. sin estar al día


class User(Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(32), primary_key=True)  # wa_id de Meta, ej. 573001234567
    profile_name: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    document_type: Mapped[str | None] = mapped_column(String(16))  # CC, TI, CE, PPT, PASAPORTE, NINGUNO
    document_id: Mapped[str | None] = mapped_column(String(32), index=True)
    id_source: Mapped[str | None] = mapped_column(String(16))
    selfie_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    id_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_attempts: Mapped[int] = mapped_column(Integer, default=0)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(40), default="START")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    reports: Mapped[list["Report"]] = relationship(back_populates="user", order_by="Report.id")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_phone: Mapped[str] = mapped_column(ForeignKey("users.phone"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ReportStatus.BORRADOR, index=True)
    report_type: Mapped[str] = mapped_column(
        String(16), default=ReportType.VIVIENDA, server_default=ReportType.VIVIENDA.value, index=True
    )

    # Ubicación
    at_property: Mapped[bool | None] = mapped_column(Boolean)
    zone: Mapped[str | None] = mapped_column(String(16))  # URBANA | RURAL
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    address_text: Mapped[str | None] = mapped_column(Text)
    municipality: Mapped[str | None] = mapped_column(String(255))

    # Situación de emergencia (ids definidos en app/content.py)
    habitability: Mapped[str | None] = mapped_column(String(32))
    injured: Mapped[bool | None] = mapped_column(Boolean)
    services: Mapped[str | None] = mapped_column(String(32))
    urgent_need: Mapped[str | None] = mapped_column(String(32))

    # Hogar
    estrato: Mapped[str | None] = mapped_column(String(16))  # "1".."6", RURAL, NO_SABE
    household_size: Mapped[int | None] = mapped_column(Integer)
    vulnerable_groups: Mapped[str | None] = mapped_column(String(255))  # "NINOS,DISCAPACIDAD" o "NINGUNO"
    ethnicity: Mapped[str | None] = mapped_column(String(32))  # dato sensible: nunca se publica
    tenure: Mapped[str | None] = mapped_column(String(32))

    # Preguntas que el ciudadano decidió saltar ("estrato,tenencia"): un dato vacío no significa "no"
    skipped_questions: Mapped[str | None] = mapped_column(Text)

    # Identidad al momento de enviar (copia de users, para trazabilidad)
    citizen_name: Mapped[str | None] = mapped_column(String(255))
    citizen_document_type: Mapped[str | None] = mapped_column(String(16))
    citizen_document_id: Mapped[str | None] = mapped_column(String(32), index=True)

    # Resultado del análisis de visión (None = sin clasificar)
    damage_level: Mapped[str | None] = mapped_column(String(16))
    damage_confidence: Mapped[float | None] = mapped_column(Float)

    confirmation_code: Mapped[str | None] = mapped_column(String(8), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="reports")
    media_files: Mapped[list["MediaFile"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="MediaFile.id"
    )
    alerts: Mapped[list["ReportAlert"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="ReportAlert.id"
    )
    business: Mapped["Business | None"] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False
    )


class Business(Base):
    """Datos propios de un reporte de negocio (report_type = NEGOCIO). Ids de opciones en app/content.py.

    La ubicación, heridos, servicios, identidad de quien reporta, fotos y alertas viven en `reports`.
    """

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), unique=True, index=True)

    # El negocio
    name: Mapped[str | None] = mapped_column(String(255))
    reporter_role: Mapped[str | None] = mapped_column(String(32))  # dueño, gerente, empleado...
    premises: Mapped[str | None] = mapped_column(String(32))  # punto de venta, bodega, ambas...
    in_home: Mapped[bool | None] = mapped_column(Boolean)  # funciona dentro de la vivienda
    operating_status: Mapped[str | None] = mapped_column(String(32))
    structural_damage: Mapped[str | None] = mapped_column(String(16))  # autoevaluación del local
    reopening_estimate: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str | None] = mapped_column(String(32))
    age_range: Mapped[str | None] = mapped_column(String(16))
    employees_range: Mapped[str | None] = mapped_column(String(16))
    jobs_at_risk: Mapped[int | None] = mapped_column(Integer)  # personas que hoy no pueden trabajar
    tenure: Mapped[str | None] = mapped_column(String(32))
    digital_sales: Mapped[bool | None] = mapped_column(Boolean)  # vende por WhatsApp, redes o domicilios
    leadership_groups: Mapped[str | None] = mapped_column(String(255))  # "MUJER,VICTIMA_CONFLICTO" o "NINGUNO"

    # Obligaciones y finanzas: solo las responde quien toma decisiones. Nunca se publican por negocio.
    # Estados: AL_DIA, PENDIENTE, NO_SABE, NO_APLICA.
    registry_status: Mapped[str | None] = mapped_column(String(16))  # Registro Mercantil y su renovación
    legal_form: Mapped[str | None] = mapped_column(String(32))  # persona natural, sociedad...
    nit: Mapped[str | None] = mapped_column(String(32), index=True)  # NIT o matrícula mercantil
    rut_status: Mapped[str | None] = mapped_column(String(16))
    einvoice_status: Mapped[str | None] = mapped_column(String(16))  # facturación electrónica DIAN
    social_security_status: Mapped[str | None] = mapped_column(String(16))
    ica_status: Mapped[str | None] = mapped_column(String(16))
    predial_status: Mapped[str | None] = mapped_column(String(16))
    monthly_sales: Mapped[str | None] = mapped_column(String(16))
    debts: Mapped[str | None] = mapped_column(String(255))  # "BANCO,GOTA_A_GOTA" o "NINGUNO"
    payment_account: Mapped[str | None] = mapped_column(String(16))  # dónde recibir un apoyo en dinero

    # Pérdidas y necesidades
    losses: Mapped[str | None] = mapped_column(String(255))  # "MERCANCIA,MAQUINARIA" o "NINGUNO"
    loss_value: Mapped[str | None] = mapped_column(String(16))  # rango, nunca se publica por negocio
    insurance: Mapped[str | None] = mapped_column(String(16))  # SI, NO, NO_SABE
    needs: Mapped[str | None] = mapped_column(String(255))  # todas las necesidades: "CREDITO,NOMINA"
    urgent_need: Mapped[str | None] = mapped_column(String(32))  # la más urgente

    # Representante legal: si quien reporta no es el dueño ni el representante, se guardan los datos que dio
    reporter_is_legal_rep: Mapped[bool | None] = mapped_column(Boolean)
    legal_rep_name: Mapped[str | None] = mapped_column(String(255))
    legal_rep_document: Mapped[str | None] = mapped_column(String(32))

    report: Mapped[Report] = relationship(back_populates="business")


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_phone: Mapped[str] = mapped_column(ForeignKey("users.phone"), index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(512))  # relativa a MEDIA_DIR
    mime: Mapped[str | None] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    meta_media_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[Report | None] = relationship(back_populates="media_files")


class ReportAlert(Base):
    __tablename__ = "report_alerts"
    __table_args__ = (UniqueConstraint("report_id", "code", name="uq_report_alert_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[Report] = relationship(back_populates="alerts")


class ProcessedMessage(Base):
    """Ids de mensajes ya procesados: Meta reintenta webhooks y no queremos responder dos veces."""

    __tablename__ = "processed_messages"

    wamid: Mapped[str] = mapped_column(String(255), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
