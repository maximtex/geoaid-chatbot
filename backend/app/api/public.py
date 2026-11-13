"""Datos públicos y anonimizados de los reportes, para el mapa de la web del equipo.

Nunca exponer aquí: nombre, documento, teléfono, dirección, fotos (cédula, selfie, daños), alertas,
código de seguimiento (es la llave del ciudadano), ni datos sensibles o socioeconómicos individuales
(pertenencia étnica, estrato, grupos vulnerables detallados).
De los negocios tampoco: nombre, NIT, representante legal, rol de quien reporta, ventas, valor de las
pérdidas, liderazgo, obligaciones (RUT, ICA...), deudas ni cuenta. De esos solo se publican totales.
"""

from app import content

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import DamageLevel, Report, ReportStatus, ReportType

router = APIRouter(prefix="/reports", tags=["Reportes públicos"])

# Obligaciones en /stats (solo totales): campo de Business -> clave pública
COMPLIANCE_KEYS = {
    "rut_status": "rut",
    "einvoice_status": "facturacion_electronica",
    "social_security_status": "seguridad_social",
    "ica_status": "ica",
    "predial_status": "predial",
}
COORDINATE_DECIMALS = 3  # ~100 m: suficiente para el mapa, sin señalar la casa exacta


class PublicReport(BaseModel):
    id: int
    report_type: str  # VIVIENDA | NEGOCIO
    municipality: str | None
    zone: str | None  # URBANA | RURAL
    lat: float | None
    lon: float | None
    damage_level: str | None  # VERDE | AMARILLO | ROJO | null (en análisis)
    status: str
    submitted_at: datetime | None
    household_size: int | None
    has_vulnerable: bool
    displaced: bool  # el hogar no puede habitar la vivienda
    injured: bool  # hay personas heridas
    urgent_need: str | None  # ALBERGUE, ALIMENTOS, AGUA, MEDICAMENTOS, ASEO, ROPA, NINGUNA
    # Solo negocios (null en viviendas)
    business_sector: str | None = None
    business_size: str | None = None  # MICRO | PEQUENA | MEDIANA | GRANDE
    business_closed: bool | None = None
    jobs_at_risk: int | None = None
    business_need: str | None = None  # la más urgente
    business_needs: list[str] | None = None  # todas las que marcó
    structural_damage: str | None = None  # SIN_DANO | MENOR | GRAVE | COLAPSO


class BusinessStats(BaseModel):
    total: int
    closed: int
    informal: int
    jobs_at_risk: int
    sells_online: int
    with_payment_account: int
    informal_lending: int  # negocios con deudas "gota a gota"
    by_sector: dict[str, int]
    by_size: dict[str, int]
    by_need: dict[str, int]  # cuenta cada necesidad marcada
    by_top_need: dict[str, int]  # la más urgente
    needs_by_size: dict[str, dict[str, int]]  # {"MICRO": {"CREDITO": 3, ...}}: para asignar apoyos por tamaño
    by_structural_damage: dict[str, int]
    compliance: dict[str, dict[str, int]]  # {"rut": {"AL_DIA": 2, "PENDIENTE": 1, ...}}


class ReportStats(BaseModel):
    total_reports: int
    total_households: int
    people_affected: int
    vulnerable_households: int
    displaced_households: int
    injured_reports: int
    by_damage_level: dict[str, int]
    by_urgent_need: dict[str, int]
    businesses: BusinessStats


def _round(value: float | None) -> float | None:
    return round(value, COORDINATE_DECIMALS) if value is not None else None


def _has_vulnerable(report: Report) -> bool:
    return bool(report.vulnerable_groups) and report.vulnerable_groups != "NINGUNO"


def _displaced(report: Report) -> bool:
    return (report.habitability or "").startswith(content.DISPLACED_PREFIX)


def _is_business(report: Report) -> bool:
    return report.report_type == ReportType.NEGOCIO and report.business is not None


def _closed(report: Report) -> bool:
    return _is_business(report) and (report.business.operating_status or "").startswith(content.BIZ_CLOSED_PREFIX)


def _size(report: Report) -> str | None:
    return content.BIZ_SIZE_BY_EMPLOYEES.get(report.business.employees_range or "") if _is_business(report) else None


def _needs(business) -> list[str]:
    return [n for n in (business.needs or "").split(",") if n and n != content.NONE_SELECTED]


def _submitted_reports(request: Request, limit: int | None = None) -> list[Report]:
    query = (
        select(Report)
        .options(selectinload(Report.business))
        .where(Report.status != ReportStatus.BORRADOR)
        .order_by(Report.submitted_at.desc(), Report.id.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    with request.app.state.session_factory() as db:
        return list(db.scalars(query).all())


@router.get("/public", response_model=list[PublicReport])
def public_reports(request: Request, limit: Annotated[int, Query(ge=1, le=2000)] = 500) -> list[PublicReport]:
    return [_public(r) for r in _submitted_reports(request, limit)]


def _public(r: Report) -> PublicReport:
    business = r.business if _is_business(r) else None
    return PublicReport(
        id=r.id,
        report_type=r.report_type,
        municipality=r.municipality,
        zone=r.zone,
        lat=_round(r.latitude),
        lon=_round(r.longitude),
        damage_level=r.damage_level,
        status=r.status,
        submitted_at=r.submitted_at,
        household_size=r.household_size,
        has_vulnerable=_has_vulnerable(r),
        displaced=_displaced(r),
        injured=bool(r.injured),
        urgent_need=r.urgent_need,
        business_sector=business.sector if business else None,
        business_size=_size(r),
        business_closed=_closed(r) if business else None,
        jobs_at_risk=business.jobs_at_risk if business else None,
        business_need=business.urgent_need if business else None,
        business_needs=_needs(business) if business else None,
        structural_damage=business.structural_damage if business else None,
    )


@router.get("/stats", response_model=ReportStats)
def report_stats(request: Request) -> ReportStats:
    reports = _submitted_reports(request)
    homes = [r for r in reports if not _is_business(r)]
    businesses = [r.business for r in reports if _is_business(r)]
    by_level = {level.value: 0 for level in DamageLevel} | {"SIN_CLASIFICAR": 0}
    by_need = {value: 0 for value, _, _ in content.URGENT_NEED_OPTIONS}
    for r in reports:
        by_level[r.damage_level if r.damage_level in by_level else "SIN_CLASIFICAR"] += 1
    for r in homes:
        if r.urgent_need in by_need:
            by_need[r.urgent_need] += 1

    by_sector = {value: 0 for value, _, _ in content.BIZ_SECTOR_OPTIONS}
    by_size = dict.fromkeys(("MICRO", "PEQUENA", "MEDIANA", "GRANDE"), 0)
    need_ids = [value for value, _, _ in content.BIZ_NEED_OPTIONS]
    by_business_need = dict.fromkeys(need_ids, 0)
    by_top_need = dict.fromkeys(need_ids, 0)
    needs_by_size = {size: dict.fromkeys(need_ids, 0) for size in by_size}
    by_damage = {value: 0 for value, _, _ in content.BIZ_STRUCTURAL_DAMAGE_OPTIONS}
    statuses = (content.STATUS_UP_TO_DATE, content.STATUS_PENDING, content.STATUS_UNKNOWN, content.STATUS_NOT_APPLICABLE)
    compliance = {"registro_mercantil": {value: 0 for value, _, _ in content.BIZ_REGISTRY_OPTIONS}} | {
        key: dict.fromkeys(statuses, 0) for key in COMPLIANCE_KEYS.values()
    }
    for b in businesses:
        if b.sector in by_sector:
            by_sector[b.sector] += 1
        size = content.BIZ_SIZE_BY_EMPLOYEES.get(b.employees_range or "")
        if size in by_size:
            by_size[size] += 1
        for need in _needs(b):
            if need in by_business_need:
                by_business_need[need] += 1
                if size in needs_by_size:
                    needs_by_size[size][need] += 1
        if b.urgent_need in by_top_need:
            by_top_need[b.urgent_need] += 1
        if b.structural_damage in by_damage:
            by_damage[b.structural_damage] += 1
        if b.registry_status in compliance["registro_mercantil"]:
            compliance["registro_mercantil"][b.registry_status] += 1
        for field, key in COMPLIANCE_KEYS.items():
            value = getattr(b, field)
            if value in statuses:
                compliance[key][value] += 1

    return ReportStats(
        total_reports=len(reports),
        total_households=len(homes),
        people_affected=sum(r.household_size or 0 for r in homes),
        vulnerable_households=sum(_has_vulnerable(r) for r in homes),
        displaced_households=sum(_displaced(r) for r in homes),
        injured_reports=sum(bool(r.injured) for r in reports),
        by_damage_level=by_level,
        by_urgent_need=by_need,
        businesses=BusinessStats(
            total=len(businesses),
            closed=sum(_closed(r) for r in reports),
            informal=sum(b.registry_status == content.BIZ_INFORMAL for b in businesses),
            jobs_at_risk=sum(b.jobs_at_risk or 0 for b in businesses),
            sells_online=sum(bool(b.digital_sales) for b in businesses),
            with_payment_account=sum(b.payment_account in ("BANCO", "BILLETERA", "AMBAS") for b in businesses),
            informal_lending=sum(content.BIZ_INFORMAL_LENDER in (b.debts or "").split(",") for b in businesses),
            by_sector=by_sector,
            by_size=by_size,
            by_need=by_business_need,
            by_top_need=by_top_need,
            needs_by_size=needs_by_size,
            by_structural_damage=by_damage,
            compliance=compliance,
        ),
    )
