"""Clasificación del daño de la vivienda a partir de fotos (semáforo de habitabilidad).

*** IMPLEMENTACIÓN SIMULADA ***
El equipo de visión (Persona 2) debe reemplazar el cuerpo de `analyze_building_damage`
manteniendo su firma.

Contrato:
- Recibe de 1 a 3 rutas absolutas de imágenes del mismo inmueble.
- Devuelve `DamageAssessment`; `level=None` significa "sin clasificar" (queda para el revisor).
- Es una función síncrona; el bot la ejecuta en un hilo aparte.

La simulación NO inventa un nivel de daño: devuelve None para no guardar una clasificación falsa.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from app.db.models import DamageLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DamageAssessment:
    level: DamageLevel | None
    confidence: float | None = None  # 0.0 a 1.0


def analyze_building_damage(image_paths: list[Path]) -> DamageAssessment:
    logger.warning("VISIÓN SIMULADA: %s foto(s) sin clasificar", len(image_paths))
    return DamageAssessment(level=None, confidence=None)
