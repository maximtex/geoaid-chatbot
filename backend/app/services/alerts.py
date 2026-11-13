"""Alertas para el revisor humano. Ninguna rechaza el reporte; solo señalan qué mirar con cuidado."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import content
from app.db.models import AlertCode, Business, MediaFile, Report, ReportAlert, ReportStatus


def add_alert(report: Report, code: AlertCode, detail: str | None = None) -> None:
    if any(alert.code == code for alert in report.alerts):
        return
    report.alerts.append(ReportAlert(code=code, detail=detail))


def evaluate_on_submit(db: Session, report: Report) -> None:
    """Reglas que se calculan al enviar el reporte. Requiere que el reporte ya tenga identidad y fotos."""
    submitted = Report.status != ReportStatus.BORRADOR

    if report.citizen_document_id:
        others = db.scalars(
            select(Report.confirmation_code).where(
                submitted,
                Report.id != report.id,
                Report.citizen_document_id == report.citizen_document_id,
                Report.user_phone != report.user_phone,
            )
        ).all()
        if others:
            add_alert(report, AlertCode.CEDULA_DUPLICADA, "Misma cédula reportada desde otro teléfono: " + ", ".join(others))

        other_ids = db.scalars(
            select(Report.citizen_document_id).where(
                submitted,
                Report.id != report.id,
                Report.user_phone == report.user_phone,
                Report.citizen_document_id != report.citizen_document_id,
            )
        ).all()
        if other_ids:
            add_alert(
                report,
                AlertCode.TELEFONO_VARIAS_CEDULAS,
                "Este teléfono reportó antes con otras cédulas: " + ", ".join(sorted(set(other_ids))),
            )

    business = report.business
    if business is not None and business.nit:
        others = db.scalars(
            select(Report.confirmation_code)
            .join(Business, Business.report_id == Report.id)
            .where(submitted, Report.id != report.id, Business.nit == business.nit, Report.user_phone != report.user_phone)
        ).all()
        if others:
            add_alert(report, AlertCode.NIT_DUPLICADO, "Mismo NIT reportado desde otro teléfono: " + ", ".join(others))

    if business is not None:
        # Informativa: algunos programas de apoyo exigen estar al día. No bloquea ni rechaza el reporte.
        pending = ["renovación del Registro Mercantil"] if business.registry_status == "SIN_RENOVAR" else []
        pending += [
            label
            for field, label in content.OBLIGATION_LABELS.items()
            if getattr(business, field) == content.STATUS_PENDING
        ]
        if pending:
            add_alert(report, AlertCode.OBLIGACIONES_PENDIENTES, "No está al día con: " + ", ".join(pending) + ".")

    repeated: set[str] = set()
    for media in report.media_files:
        matches = db.scalars(
            select(MediaFile.report_id).where(
                MediaFile.sha256 == media.sha256,
                MediaFile.report_id != report.id,
                MediaFile.id != media.id,
            )
        ).all()
        repeated.update(str(report_id) for report_id in matches if report_id is not None)
    if repeated:
        add_alert(report, AlertCode.FOTO_REPETIDA, "Foto idéntica en reporte(s) id: " + ", ".join(sorted(repeated)))

    if report.at_property is False and report.latitude is not None:
        add_alert(
            report,
            AlertCode.GPS_FUERA_DE_VIVIENDA,
            "El ciudadano no estaba en el inmueble: el GPS es su ubicación actual, no la del inmueble.",
        )
