"""Almacenamiento local de fotos. La carpeta NO se publica por HTTP: contiene datos personales."""

import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import MediaFile, Report

logger = logging.getLogger(__name__)

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}


def store_media(
    db: Session,
    media_dir: Path,
    *,
    report: Report,
    kind: str,
    content: bytes,
    mime: str | None,
    meta_media_id: str | None,
) -> MediaFile:
    extension = _EXTENSIONS.get(mime or "", ".bin")
    relative = Path(report.user_phone) / str(report.id) / f"{kind.lower()}_{uuid.uuid4().hex}{extension}"
    absolute = media_dir / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(content)

    media = MediaFile(
        user_phone=report.user_phone,
        kind=kind,
        path=relative.as_posix(),
        mime=mime,
        sha256=hashlib.sha256(content).hexdigest(),
        meta_media_id=meta_media_id,
    )
    report.media_files.append(media)
    db.flush()
    return media


def absolute_path(media_dir: Path, media: MediaFile) -> Path:
    return media_dir / media.path


def delete_files(media_dir: Path, media_files: list[MediaFile]) -> None:
    for media in media_files:
        try:
            absolute_path(media_dir, media).unlink(missing_ok=True)
        except OSError:
            logger.exception("No se pudo borrar %s", media.path)
