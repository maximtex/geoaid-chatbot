# Imagen lista para desplegar en la nube (Railway, Render, Fly). No se usa en la demo local.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Si el OCR o la visión necesitan librerías del sistema (p. ej. OpenCV), agregarlas aquí:
# RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# En la nube: montar un volumen en /data para que la base y las fotos sobrevivan a los reinicios.
ENV DATABASE_URL=sqlite:////data/geoaid.db \
    MEDIA_DIR=/data/media

EXPOSE 8000
CMD ["sh", "-c", "mkdir -p /data && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
