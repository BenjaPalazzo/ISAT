"""
pipeline.py — Pipeline ISCE2 real para procesamiento InSAR
Pasos: co-registro → interferograma → unwrapping (SNAPHU) → geocodificación → PNG

Sin mock, sin base de datos.
"""

import logging
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

log = logging.getLogger(__name__)


# ── Excepciones y resultado ───────────────────────────────────────────────────

class PipelineError(Exception):
    """Error controlado del pipeline ISCE2."""


@dataclass
class PipelineResult:
    output_image:   Path
    mean_coherence: float
    bbox_wkt:       str
    processed_at:   str


# ── Pipeline principal ────────────────────────────────────────────────────────

class ISCEPipeline:
    """
    Orquesta los 4 pasos del pipeline InSAR sobre un par Sentinel-1
    usando topsApp.py de ISCE2.

    Pasos:
        1. Co-registro          (topsApp --end=preprocess)
        2. Interferograma       (topsApp --start=computeBaselines --end=filter)
        3. Unwrapping SNAPHU    (topsApp --start=unwrap --end=unwrap)
        4. Geocodificación      (topsApp --start=geocode --end=geocode) + export PNG
    """

    # Longitud de onda Sentinel-1 en cm (banda C, ~5.405 GHz)
    LAMBDA_CM = 5.5465

    def __init__(
        self,
        reference_image: Path,
        secondary_image: Path,
        work_dir:        Path,
        output_dir:      Path,
        job_id:          str,
    ):
        self.reference  = Path(reference_image)
        self.secondary  = Path(secondary_image)
        self.work_dir   = Path(work_dir)
        self.output_dir = Path(output_dir)
        self.job_id     = job_id
        self.log_path   = self.work_dir / "isce.log"

        self._setup_file_logger()

    # ── Entrada pública ───────────────────────────────────────────────────────

    def run(self) -> PipelineResult:
        log.info("[%s] Iniciando pipeline ISCE2", self.job_id)
        try:
            self._step_coregister()
            ifg_path = self._step_interferogram()
            unw_path = self._step_unwrap(ifg_path)
            result   = self._step_geocode_and_export(unw_path)
            log.info("[%s] Pipeline completado exitosamente", self.job_id)
            return result
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(f"Error inesperado en pipeline: {e}") from e

    # ── Pasos del pipeline ────────────────────────────────────────────────────

    def _step_coregister(self):
        """Paso 1: Co-registro de las dos imágenes Sentinel-1."""
        log.info("[%s] Paso 1/4: co-registro", self.job_id)
        config = self._write_topsapp_xml()
        self._run_isce_command(
            ["topsApp.py", str(config), "--end=preprocess"],
            step_name="coregister",
        )

    def _step_interferogram(self) -> Path:
        """Paso 2: Generación del interferograma y filtrado."""
        log.info("[%s] Paso 2/4: interferograma", self.job_id)
        config = self.work_dir / "topsApp.xml"
        self._run_isce_command(
            ["topsApp.py", str(config), "--start=computeBaselines", "--end=filter"],
            step_name="interferogram",
        )

        ifg_path = self.work_dir / "merged" / "filt_topophase.flat"
        if not ifg_path.exists():
            raise PipelineError(f"Interferograma no generado: {ifg_path}")
        return ifg_path

    def _step_unwrap(self, ifg_path: Path) -> Path:
        """Paso 3: Phase unwrapping con SNAPHU."""
        log.info("[%s] Paso 3/4: unwrapping (SNAPHU)", self.job_id)
        self._run_isce_command(
            ["topsApp.py", str(self.work_dir / "topsApp.xml"), "--start=unwrap", "--end=unwrap"],
            step_name="unwrap",
        )

        unw_path = self.work_dir / "merged" / "filt_topophase.unw"
        if not unw_path.exists():
            raise PipelineError(f"Unwrapped no generado: {unw_path}")
        return unw_path

    def _step_geocode_and_export(self, unw_path: Path) -> PipelineResult:
        """Paso 4: Geocodificación y exportación del mapa de deformación."""
        log.info("[%s] Paso 4/4: geocodificación y exportación PNG", self.job_id)

        self._run_isce_command(
            ["topsApp.py", str(self.work_dir / "topsApp.xml"), "--start=geocode", "--end=geocode"],
            step_name="geocode",
        )

        # Preferir versión geocodificada; fallback al unwrapped crudo
        geo_path = self.work_dir / "merged" / "filt_topophase.unw.geo"
        if not geo_path.exists():
            log.warning("[%s] Geocodificado no encontrado, usando unwrapped directo", self.job_id)
            geo_path = unw_path

        phase_data, mean_coherence = self._read_phase_and_coherence(geo_path)
        output_png = self._export_png(phase_data)
        bbox_wkt   = self._extract_bbox_wkt()

        return PipelineResult(
            output_image   = output_png,
            mean_coherence = mean_coherence,
            bbox_wkt       = bbox_wkt,
            processed_at   = datetime.now(timezone.utc).isoformat(),
        )

    # ── Helpers internos ──────────────────────────────────────────────────────

    def _write_topsapp_xml(self) -> Path:
        """
        Genera el archivo topsApp.xml de configuración para este par de imágenes.

        TODO: agregar más parámetros según necesidad:
            - número de burst por subswath
            - DEM externo (si no usás el automático)
            - máscara de agua
            - parámetros de SNAPHU (modo SMOOTH vs DEFO)
        """
        xml_path = self.work_dir / "topsApp.xml"
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<topsApp>
  <component name="topsinsar">
    <property name="Sensor name">SENTINEL1</property>

    <component name="reference">
      <property name="safe">[ "{self.reference}" ]</property>
      <property name="output directory">reference</property>
      <!-- TODO: agregar orbit file si los tenés descargados localmente -->
      <!-- <property name="orbit directory">/path/to/orbits</property> -->
    </component>

    <component name="secondary">
      <property name="safe">[ "{self.secondary}" ]</property>
      <property name="output directory">secondary</property>
    </component>

    <property name="working directory">{self.work_dir}</property>

    <!-- Unwrapping con SNAPHU -->
    <property name="do unwrap">True</property>
    <property name="unwrapper name">snaphu</property>
    <!-- TODO: cambiar a SMOOTH si el área tiene deformación suave (ej: subsidencia lenta) -->
    <!-- <property name="unwrapper snaphu statistics-cost mode">DEFO</property> -->

    <!-- Geocodificación -->
    <property name="do geocode">True</property>

    <!-- TODO: especificar DEM externo si lo tenés (mejora la calidad) -->
    <!-- <property name="dem filename">/path/to/dem.dem.wgs84</property> -->

    <!-- TODO: recortar a área de interés (lat/lon min-max) -->
    <!-- <property name="geocode bounding box">[-33.5, -69.5, -32.8, -68.5]</property> -->

  </component>
</topsApp>
"""
        xml_path.write_text(content)
        log.info("[%s] topsApp.xml generado en %s", self.job_id, xml_path)
        return xml_path

    def _run_isce_command(self, cmd: list, step_name: str):
        """
        Ejecuta un comando de ISCE2 y loguea stdout/stderr.
        Timeout de 1 hora por paso (ajustar si las imágenes son muy grandes).
        """
        log.info("[%s] Ejecutando: %s", self.job_id, " ".join(str(c) for c in cmd))
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.work_dir),
                capture_output=True,
                text=True,
                timeout=3600,
            )
            with open(self.log_path, "a") as f:
                f.write(f"\n{'='*40}\n[PASO: {step_name}]\n{'='*40}\n")
                f.write(result.stdout or "")
                if result.stderr:
                    f.write("\n--- STDERR ---\n")
                    f.write(result.stderr)

            if result.returncode != 0:
                # Incluir las últimas 800 chars de stderr para diagnóstico
                tail = (result.stderr or "")[-800:]
                raise PipelineError(
                    f"Falló paso '{step_name}' (exit code {result.returncode}):\n{tail}"
                )

        except subprocess.TimeoutExpired:
            raise PipelineError(f"Timeout (>3600s) en paso: {step_name}")

    def _read_phase_and_coherence(self, geo_path: Path):
        """
        Lee el archivo .unw.geo generado por ISCE2.
        Formato BIL: banda 1 = coherencia, banda 2 = fase unwrapped (radianes).
        """
        try:
            # Intentar con la API de ISCE2 directamente
            from isceobj.Image.Image import Image
            img = Image()
            img.load(str(geo_path) + ".xml")
            rows, cols = img.length, img.width
            mm = np.memmap(str(geo_path), dtype=np.float32, mode="r", shape=(rows, cols * 2))
            coherence = mm[:, 0::2].copy()
            phase     = mm[:, 1::2].copy()
            del mm

        except Exception as e:
            log.warning("[%s] Lectura via ISCE API falló (%s), usando fallback binario", self.job_id, e)
            # Fallback: leer el binario plano y asumir layout BIL
            raw  = np.fromfile(str(geo_path), dtype=np.float32)
            half = len(raw) // 2
            # Intentar reconstruir forma cuadrada aproximada
            side = int(np.sqrt(half))
            coherence = raw[:half].reshape(side, -1)
            phase     = raw[half:].reshape(side, -1)

        # Enmascarar píxeles de baja coherencia (< 0.3 es poco confiable)
        mask          = coherence > 0.3
        phase_masked  = np.where(mask, phase, np.nan)
        mean_coh      = float(np.nanmean(coherence))

        log.info("[%s] Coherencia media: %.3f", self.job_id, mean_coh)
        return phase_masked, mean_coh

    def _export_png(self, phase_data: np.ndarray) -> Path:
        """
        Convierte la fase unwrapped a deformación en cm y exporta un PNG de dos paneles:
        - Panel izquierdo: mapa de deformación con colormap RdBu_r
        - Panel derecho:   histograma de valores
        """
        output_path = self.output_dir / f"deformation_{self.job_id}.png"

        # Fase [rad] → deformación [cm]   d = φ · λ / (4π)
        deformation = phase_data * self.LAMBDA_CM / (4 * np.pi)

        vmax = np.nanpercentile(np.abs(deformation), 98)
        vmin = -vmax

        fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=130)
        fig.patch.set_facecolor("#0f0f0f")

        # ── Panel izquierdo: mapa de deformación ──────────────────────────────
        ax1 = axes[0]
        im  = ax1.imshow(deformation, cmap="RdBu_r", vmin=vmin, vmax=vmax,
                         interpolation="bilinear")
        cbar = fig.colorbar(im, ax=ax1, fraction=0.046, pad=0.04)
        cbar.set_label("Deformación (cm)", color="white", fontsize=10)
        cbar.ax.yaxis.set_tick_params(color="white")
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white")
        ax1.set_title("Mapa de deformación LOS", color="white", fontsize=12, pad=10)
        ax1.set_facecolor("#1a1a2e")
        ax1.tick_params(colors="white")
        for spine in ax1.spines.values():
            spine.set_edgecolor("#444")

        min_val = np.nanmin(deformation)
        max_val = np.nanmax(deformation)
        ax1.set_xlabel(
            f"Min: {min_val:.1f} cm  |  Max: {max_val:.1f} cm",
            color="#aaa", fontsize=9
        )

        # ── Panel derecho: histograma ─────────────────────────────────────────
        ax2    = axes[1]
        valid  = deformation[~np.isnan(deformation)].flatten()
        ax2.hist(valid, bins=80, color="#4a90d9", edgecolor="none", alpha=0.85)
        ax2.axvline(0, color="white", linewidth=1, linestyle="--", alpha=0.6)
        ax2.set_facecolor("#1a1a2e")
        ax2.set_title("Distribución de deformación", color="white", fontsize=12, pad=10)
        ax2.set_xlabel("Deformación (cm)", color="white", fontsize=10)
        ax2.set_ylabel("Número de píxeles", color="white", fontsize=10)
        ax2.tick_params(colors="white")
        for spine in ax2.spines.values():
            spine.set_edgecolor("#444")

        fig.suptitle(
            f"Job {self.job_id[:8]} — Sentinel-1 InSAR (ISCE2)",
            color="white", fontsize=13, y=1.01,
        )
        plt.tight_layout()
        plt.savefig(str(output_path), format="png", bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)

        log.info("[%s] PNG exportado: %s", self.job_id, output_path)
        return output_path

    def _extract_bbox_wkt(self) -> str:
        """
        Extrae el bounding box del área procesada desde el XML de geocodificado de ISCE2.
        Devuelve WKT en EPSG:4326.
        """
        geo_xml = self.work_dir / "merged" / "filt_topophase.unw.geo.xml"
        try:
            if geo_xml.exists():
                tree = ET.parse(str(geo_xml))
                root = tree.getroot()
                lat1 = float(root.findtext(".//property[@name='minimum latitude']/value",  "0"))
                lat2 = float(root.findtext(".//property[@name='maximum latitude']/value",  "0"))
                lon1 = float(root.findtext(".//property[@name='minimum longitude']/value", "0"))
                lon2 = float(root.findtext(".//property[@name='maximum longitude']/value", "0"))
                wkt  = (
                    f"POLYGON(({lon1} {lat1}, {lon2} {lat1}, "
                    f"{lon2} {lat2}, {lon1} {lat2}, {lon1} {lat1}))"
                )
                log.info("[%s] BBox extraído: %s", self.job_id, wkt)
                return wkt
        except Exception as e:
            log.warning("[%s] No se pudo extraer bbox: %s", self.job_id, e)

        # TODO: si el geocodificado no genera el XML, hardcodear el área de interés
        # como fallback temporal mientras validás el pipeline:
        # return "POLYGON((-69.5 -32.8, -68.5 -32.8, -68.5 -33.5, -69.5 -33.5, -69.5 -32.8))"
        return "POLYGON((0 0, 0 0, 0 0, 0 0, 0 0))"

    def _setup_file_logger(self):
        """Agrega un FileHandler al logger raíz para guardar logs del job en disco."""
        handler = logging.FileHandler(str(self.log_path))
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(handler)