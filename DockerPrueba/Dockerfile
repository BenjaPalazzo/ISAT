# Dockerfile — Docker ISCE2 con API REST integrada
# Base: imagen oficial de isce2 con Python 3.8

FROM isce/isce2:latest

# ── Dependencias Python para la API ──────────────────────────────────────────
FROM isce/isce2:latest

# Instalar pip
RUN apt-get update && apt-get install -y python3-pip

# Instalar dependencias Python
RUN python3 -m pip install --no-cache-dir \
    flask==3.0.3 \
    gunicorn==22.0.0 \
    Pillow==10.3.0 \
    matplotlib==3.7.5 \
    psycopg2-binary==2.9.9

# ── Copiar código del pipeline y API ─────────────────────────────────────────
WORKDIR /app
COPY api_server.py .
COPY pipeline.py   .

# ── Directorios de trabajo ────────────────────────────────────────────────────
RUN mkdir -p /tmp/isce_jobs /tmp/isce_output

# ── Variables de entorno ──────────────────────────────────────────────────────
ENV WORK_DIR=/tmp/isce_jobs
ENV OUTPUT_DIR=/tmp/isce_output
ENV PORT=5000

# ── Exponer puerto ────────────────────────────────────────────────────────────
EXPOSE 5000

# ── Arrancar con gunicorn (producción) ────────────────────────────────────────
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "3600", \
     "--log-level", "info", \
     "api_server:app"]