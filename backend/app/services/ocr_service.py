"""Lectura de la cédula de ciudadanía (OCR).

*** IMPLEMENTACIÓN SIMULADA ***
El equipo de OCR (Persona 3) debe reemplazar el cuerpo de `extract_id_data` manteniendo su firma.

Contrato:
- Recibe la ruta absoluta de una imagen (JPEG/PNG/WebP) del frente de la cédula.
- Devuelve `IdData`. Si no se pudo leer algún campo, debe ir en None: el bot pedirá otra foto
  y, tras varios intentos, que el ciudadano escriba los datos a mano.
- Es una función síncrona; el bot la ejecuta en un hilo aparte (puede tardar varios segundos).
- No debe lanzar excepciones por imágenes ilegibles; solo por errores inesperados.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdData:
    full_name: str | None
    document_id: str | None  # solo dígitos
    confidence: float = 0.0  # 0.0 a 1.0

    @property
    def is_complete(self) -> bool:
        return bool(self.full_name and self.document_id)


def extract_id_data(image_path: Path) -> IdData:
    logger.warning("OCR SIMULADO: devolviendo datos de prueba para %s", image_path.name)
    return IdData(full_name="CIUDADANO DE PRUEBA", document_id="1000000000", confidence=0.0)
