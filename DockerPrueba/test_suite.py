"""
test_suite.py — Tests completos del sistema ISAT
Levanta la API con el mock pipeline y valida todos los endpoints.
"""

import io
import sys
import json
import time
import threading
import requests
import zipfile
import numpy as np
from pathlib import Path
from datetime import datetime

# ── Usar mock pipeline en lugar de ISCE2 real ─────────────────────────────────
import importlib, sys as _sys
import mock_pipeline
_sys.modules["pipeline"] = mock_pipeline

import api_server
app = api_server.app
app.config["TESTING"] = True


BASE_URL = "http://127.0.0.1:7654"
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

results = []

# ── Helpers ───────────────────────────────────────────────────────────────────

def run_server():
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=7654, debug=False, use_reloader=False)


def fake_sentinel_zip(name: str) -> bytes:
    """Genera un archivo .zip falso que simula un archivo Sentinel-1."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.safe", f"<SAFE><name>{name}</name></SAFE>")
        zf.writestr("measurement/s1a-iw1-slc-vv.tiff", b"\x00" * 1024)
    return buf.getvalue()


def check(label: str, condition: bool, detail: str = ""):
    icon = PASS if condition else FAIL
    results.append(condition)
    detail_str = f"  ({detail})" if detail else ""
    print(f"  {icon}  {label}{detail_str}")
    return condition


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health():
    print(f"\n{INFO} Test 1: Health check")
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    check("Status code 200",          r.status_code == 200)
    check("Campo 'status' = ok",       r.json().get("status") == "ok")
    check("Campo 'timestamp' presente", "timestamp" in r.json())


def test_process_valid():
    print(f"\n{INFO} Test 2: POST /process con imágenes válidas")

    ref_zip = fake_sentinel_zip("S1A_IW_SLC__1S_20230101")
    sec_zip = fake_sentinel_zip("S1A_IW_SLC__1S_20230113")

    files = {
        "reference": ("reference.zip", ref_zip, "application/zip"),
        "secondary": ("secondary.zip", sec_zip, "application/zip"),
    }
    data = {"job_id": "test-job-001"}

    t0 = time.time()
    r  = requests.post(f"{BASE_URL}/process", files=files, data=data, timeout=60)
    elapsed = time.time() - t0

    check("Status code 200",              r.status_code == 200,
          f"got {r.status_code}" if r.status_code != 200 else "")
    check("Content-Type es image/png",    "image/png" in r.headers.get("Content-Type",""))
    check("Header X-Job-Id presente",     "X-Job-Id" in r.headers)
    check("Header X-Coherence presente",  "X-Coherence" in r.headers)
    check("Header X-BboxWKT presente",    "X-BboxWKT" in r.headers)
    check("Respuesta contiene bytes PNG", r.content[:4] == b"\x89PNG",
          f"primeros bytes: {r.content[:4]}")
    check("PNG tiene tamaño razonable",   len(r.content) > 50_000,
          f"{len(r.content):,} bytes")
    check(f"Tiempo de respuesta < 30s",   elapsed < 30,
          f"{elapsed:.1f}s")

    # Guardar el PNG generado para inspección visual
    import tempfile
    out = Path(tempfile.gettempdir()) / "test_output.png"
    out.write_bytes(r.content)
    print(f"     PNG guardado en: {out}")

    coherence = float(r.headers.get("X-Coherence", 0))
    check("Coherencia entre 0 y 1",       0 < coherence < 1, f"{coherence:.3f}")
    check("BboxWKT contiene POLYGON",     "POLYGON" in r.headers.get("X-BboxWKT",""))

    return r.headers.get("X-Job-Id", "test-job-001")


def test_status(job_id: str):
    print(f"\n{INFO} Test 3: GET /status/<job_id>")

    r = requests.get(f"{BASE_URL}/status/{job_id}", timeout=5)
    check("Status code 200",             r.status_code == 200)
    check("Campo 'status' presente",     "status" in r.json())
    check("Status es 'done'",            r.json().get("status") == "done",
          r.json().get("status",""))

    r404 = requests.get(f"{BASE_URL}/status/job-inexistente-xyz", timeout=5)
    check("Job inexistente devuelve 404", r404.status_code == 404)


def test_process_invalid():
    print(f"\n{INFO} Test 4: Validaciones de errores")

    # Sin archivos
    r = requests.post(f"{BASE_URL}/process", timeout=5)
    check("Sin archivos → 400",           r.status_code == 400)

    # Solo un archivo
    files = {"reference": ("ref.zip", b"data", "application/zip")}
    r = requests.post(f"{BASE_URL}/process", files=files, timeout=5)
    check("Solo un archivo → 400",        r.status_code == 400)

    # Extensión no permitida
    files = {
        "reference": ("ref.jpg", b"data", "image/jpeg"),
        "secondary": ("sec.jpg", b"data", "image/jpeg"),
    }
    r = requests.post(f"{BASE_URL}/process", files=files, timeout=5)
    check("Extensión .jpg → 400",         r.status_code == 400)


def test_png_quality():
    print(f"\n{INFO} Test 5: Calidad del PNG generado")
    from PIL import Image

    import tempfile
    img_path = Path(tempfile.gettempdir()) / "test_output.png"
    if not img_path.exists():
        print("  ⚠  PNG no encontrado, saltando test de calidad")
        return

    img = Image.open(img_path)
    check("Modo RGB o RGBA",    img.mode in ("RGB", "RGBA"))
    check("Ancho > 800px",      img.width  > 800, f"{img.width}px")
    check("Alto  > 400px",      img.height > 400, f"{img.height}px")

    arr = np.array(img.convert("RGB"))
    unique_colors = len(np.unique(arr.reshape(-1, 3), axis=0))
    check("Imagen colorida (>1000 colores únicos)", unique_colors > 1000,
          f"{unique_colors:,} colores")


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  ISAT InSAR — Test Suite")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # Levantar servidor en hilo separado
    print(f"\n{INFO} Levantando servidor Flask en puerto 7654...")
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(1.5)

    try:
        test_health()
        job_id = test_process_valid()
        test_status(job_id)
        test_process_invalid()
        test_png_quality()
    except requests.ConnectionError as e:
        print(f"\n{FAIL} No se pudo conectar al servidor: {e}")
        sys.exit(1)

    # Resumen
    passed = sum(results)
    total  = len(results)
    print("\n" + "=" * 55)
    color  = "\033[92m" if passed == total else "\033[93m"
    print(f"  {color}Resultado: {passed}/{total} tests pasaron\033[0m")
    print("=" * 55)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()