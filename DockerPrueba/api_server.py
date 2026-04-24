"""
api_server.py — Servidor REST para el Docker ISCE2
Recibe dos imágenes Sentinel-1, lanza el pipeline y devuelve el mapa de deformación.
"""

import os
import uuid
import logging
import traceback
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_file
from pipeline import ISCEPipeline, PipelineError

# ── Configuración ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

WORK_DIR  = Path(os.environ.get("WORK_DIR",  "/tmp/isce_jobs"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/tmp/isce_output"))

WORK_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".zip", ".tiff", ".tif", ".safe"}

# ── Helpers ──────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def save_upload(file, dest_dir: Path) -> Path:
    filename = Path(file.filename).name
    path = dest_dir / filename
    file.save(str(path))
    return path


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Verifica que el servidor esté activo."""
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


@app.route("/process", methods=["POST"])
def process():
    """
    Recibe un par de imágenes Sentinel-1 y genera el mapa de deformación.

    Form-data esperado:
        reference  — imagen de referencia (master)
        secondary  — imagen secundaria (slave)
        job_id     — (opcional) identificador externo

    Respuesta:
        200 — imagen PNG del mapa de deformación
        400 — error de validación
        500 — error de procesamiento
    """
    # Validar archivos
    if "reference" not in request.files or "secondary" not in request.files:
        return jsonify({"error": "Se requieren los campos 'reference' y 'secondary'"}), 400

    ref_file = request.files["reference"]
    sec_file = request.files["secondary"]

    if not allowed_file(ref_file.filename) or not allowed_file(sec_file.filename):
        return jsonify({"error": f"Extensión no permitida. Usar: {ALLOWED_EXTENSIONS}"}), 400

    # Crear directorio de trabajo para este job
    job_id  = request.form.get("job_id") or str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    log.info("Iniciando job %s", job_id)

    try:
        # Guardar uploads
        ref_path = save_upload(ref_file, job_dir)
        sec_path = save_upload(sec_file, job_dir)

        # Correr pipeline
        pipeline = ISCEPipeline(
            reference_image=ref_path,
            secondary_image=sec_path,
            work_dir=job_dir,
            output_dir=OUTPUT_DIR,
            job_id=job_id,
        )
        result = pipeline.run()

        log.info("Job %s completado → %s", job_id, result.output_image)

        # Devolver imagen + metadata en headers
        response = send_file(
            str(result.output_image),
            mimetype="image/png",
            as_attachment=False,
            download_name=f"deformation_{job_id}.png",
        )
        response.headers["X-Job-Id"]       = job_id
        response.headers["X-Coherence"]    = str(result.mean_coherence)
        response.headers["X-BboxWKT"]      = result.bbox_wkt
        response.headers["X-ProcessedAt"]  = result.processed_at
        return response

    except PipelineError as e:
        log.error("Error en pipeline job %s: %s", job_id, e)
        return jsonify({"error": str(e), "job_id": job_id}), 500

    except Exception:
        log.error("Error inesperado job %s:\n%s", job_id, traceback.format_exc())
        return jsonify({"error": "Error interno del servidor", "job_id": job_id}), 500


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    """Consulta el estado de un job (útil si se implementa procesamiento async)."""
    job_dir = WORK_DIR / job_id
    if not job_dir.exists():
        return jsonify({"error": "Job no encontrado"}), 404

    output_img = OUTPUT_DIR / f"deformation_{job_id}.png"
    if output_img.exists():
        return jsonify({"job_id": job_id, "status": "done", "output": str(output_img)})

    log_file = job_dir / "isce.log"
    if log_file.exists():
        return jsonify({"job_id": job_id, "status": "processing"})

    return jsonify({"job_id": job_id, "status": "pending"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)