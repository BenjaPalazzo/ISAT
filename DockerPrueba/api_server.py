"""
api_server.py — Servidor REST para el Docker ISCE2 (producción)
Recibe dos imágenes Sentinel-1 via HTTP, lanza el pipeline ISCE2 real
y devuelve el mapa de deformación como PNG con metadata en headers.

Sin mock, sin base de datos.
"""

import os
import uuid
import logging
import traceback
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_file
from pipeline import ISCEPipeline, PipelineError

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ── App Flask ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

# TODO: configurar límite de tamaño para uploads grandes (Sentinel-1 ~4 GB c/u)
# app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024**3))

WORK_DIR   = Path(os.environ.get("WORK_DIR",   "/tmp/isce_jobs"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/tmp/isce_output"))

WORK_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".zip", ".tiff", ".tif", ".safe"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def save_upload(file, dest_dir: Path) -> Path:
    """Guarda el archivo subido en el directorio de trabajo del job."""
    filename = Path(file.filename).name
    path = dest_dir / filename
    file.save(str(path))
    log.info("Archivo guardado: %s (%.1f MB)", path, path.stat().st_size / 1e6)
    return path


# ── Autenticación simple (opcional) ──────────────────────────────────────────
# TODO: descomentar y configurar API_SECRET_KEY en el entorno para proteger
#       el endpoint cuando esté expuesto a internet.
#
# from functools import wraps
# def require_api_key(f):
#     @wraps(f)
#     def decorated(*args, **kwargs):
#         key = request.headers.get("X-API-Key") or request.args.get("api_key")
#         if key != os.environ.get("API_SECRET_KEY"):
#             return jsonify({"error": "Unauthorized"}), 401
#         return f(*args, **kwargs)
#     return decorated


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """
    GET /health
    Verifica que el servidor esté activo y listo para recibir imágenes.
    Útil para health-checks del servidor remoto antes de enviar datos.
    """
    return jsonify({
        "status":    "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "work_dir":  str(WORK_DIR),
        "output_dir": str(OUTPUT_DIR),
    })


@app.route("/process", methods=["POST"])
# @require_api_key  # TODO: descomentar cuando tengas la auth configurada
def process():
    """
    POST /process
    Recibe un par de imágenes Sentinel-1 y genera el mapa de deformación InSAR.

    Form-data esperado:
        reference  — imagen de referencia (.zip / .SAFE / .tiff)
        secondary  — imagen secundaria   (.zip / .SAFE / .tiff)
        job_id     — (opcional) ID externo para tracking

    Respuesta exitosa (200):
        Content-Type: image/png
        X-Job-Id        — identificador del job
        X-Coherence     — coherencia media [0.0 – 1.0]
        X-BboxWKT       — bounding box en WKT (EPSG:4326)
        X-ProcessedAt   — timestamp ISO 8601 UTC

    Errores:
        400 — falta algún campo o extensión no permitida
        500 — fallo en el pipeline ISCE2
    """
    # ── Validar presencia de archivos ──────────────────────────────────────────
    if "reference" not in request.files or "secondary" not in request.files:
        return jsonify({
            "error": "Se requieren los campos 'reference' y 'secondary'",
            "hint":  "Enviar como multipart/form-data"
        }), 400

    ref_file = request.files["reference"]
    sec_file = request.files["secondary"]

    if not ref_file.filename or not sec_file.filename:
        return jsonify({"error": "Los archivos no tienen nombre"}), 400

    if not allowed_file(ref_file.filename) or not allowed_file(sec_file.filename):
        return jsonify({
            "error":      "Extensión de archivo no permitida",
            "allowed":    list(ALLOWED_EXTENSIONS),
            "got":        [ref_file.filename, sec_file.filename],
        }), 400

    # ── Crear directorio de trabajo para el job ────────────────────────────────
    job_id  = request.form.get("job_id") or str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== Iniciando job %s ===", job_id)

    try:
        # ── Guardar uploads ────────────────────────────────────────────────────
        ref_path = save_upload(ref_file, job_dir)
        sec_path = save_upload(sec_file, job_dir)

        # ── Ejecutar pipeline ISCE2 ────────────────────────────────────────────
        pipeline = ISCEPipeline(
            reference_image = ref_path,
            secondary_image = sec_path,
            work_dir        = job_dir,
            output_dir      = OUTPUT_DIR,
            job_id          = job_id,
        )
        result = pipeline.run()

        log.info("=== Job %s completado → %s ===", job_id, result.output_image)

        # ── Devolver PNG + metadata en headers ─────────────────────────────────
        response = send_file(
            str(result.output_image),
            mimetype="image/png",
            as_attachment=False,
            download_name=f"deformation_{job_id}.png",
        )
        response.headers["X-Job-Id"]       = job_id
        response.headers["X-Coherence"]    = f"{result.mean_coherence:.4f}"
        response.headers["X-BboxWKT"]      = result.bbox_wkt
        response.headers["X-ProcessedAt"]  = result.processed_at

        # Exponer headers para clientes CORS si los necesitás después
        response.headers["Access-Control-Expose-Headers"] = (
            "X-Job-Id, X-Coherence, X-BboxWKT, X-ProcessedAt"
        )
        return response

    except PipelineError as e:
        log.error("Error controlado en job %s: %s", job_id, e)
        return jsonify({"error": str(e), "job_id": job_id}), 500

    except Exception:
        log.error("Error inesperado en job %s:\n%s", job_id, traceback.format_exc())
        return jsonify({"error": "Error interno del servidor", "job_id": job_id}), 500


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    """
    GET /status/<job_id>
    Consulta el estado de un job por su ID.

    Útil para que el servidor remoto verifique si el procesamiento
    terminó sin tener que esperar bloqueado en el POST /process.

    Respuesta:
        { "job_id": "...", "status": "pending" | "processing" | "done" | "failed" }
    """
    job_dir = WORK_DIR / job_id
    if not job_dir.exists():
        return jsonify({"error": "Job no encontrado", "job_id": job_id}), 404

    output_img = OUTPUT_DIR / f"deformation_{job_id}.png"
    if output_img.exists():
        return jsonify({
            "job_id":  job_id,
            "status":  "done",
            "output":  str(output_img),
            "size_mb": round(output_img.stat().st_size / 1e6, 2),
        })

    log_file = job_dir / "isce.log"
    if log_file.exists():
        return jsonify({"job_id": job_id, "status": "processing"})

    return jsonify({"job_id": job_id, "status": "pending"})


# ── Entry point (desarrollo local) ────────────────────────────────────────────
# En producción arranca gunicorn desde el CMD del Dockerfile.

if __name__ == "__main__":
    # TODO: reemplazar con tu puerto preferido para pruebas locales
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)