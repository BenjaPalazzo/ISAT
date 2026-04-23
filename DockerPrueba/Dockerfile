FROM isce/isce2:latest

# ── Dependencias del sistema (incluye pip + libs para matplotlib) ─────────────
RUN apt-get update && apt-get install -y \
    python3-pip \
    libfreetype6-dev \
    libpng-dev \
    pkg-config

# ── Dependencias Python ───────────────────────────────────────────────────────
RUN pip3 install --no-cache-dir \
    flask==3.0.3 \
    gunicorn==22.0.0 \
    Pillow==10.3.0 \
    matplotlib==3.7.5

# ── Código ────────────────────────────────────────────────────────────────────
WORKDIR /app
COPY api_server.py .
COPY pipeline.py .

# ── Directorios ───────────────────────────────────────────────────────────────
RUN mkdir -p /tmp/isce_jobs /tmp/isce_output

# ── Variables de entorno ──────────────────────────────────────────────────────
ENV WORK_DIR=/tmp/isce_jobs
ENV OUTPUT_DIR=/tmp/isce_output
ENV PORT=5000

# ── Puerto ────────────────────────────────────────────────────────────────────
EXPOSE 5000

# ── Run ───────────────────────────────────────────────────────────────────────
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "3600", "--log-level", "info", "api_server:app"]