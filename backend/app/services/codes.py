import secrets

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import Report

# Sin 0/O ni 1/I/L para que el ciudadano no se confunda al dictarlo o escribirlo.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def unique_confirmation_code(db: Session) -> str:
    for _ in range(20):
        code = new_code()
        if not db.scalar(select(exists().where(Report.confirmation_code == code))):
            return code
    raise RuntimeError("No se pudo generar un código único")
