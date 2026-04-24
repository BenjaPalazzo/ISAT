"""
pipeline.py — Wrapper del pipeline ISCE2 para procesamiento InSAR
Encadena: co-registro → interferograma → unwrapping → geocodificación → PNG
"""

import os
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
    
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

log = logging.getLogger(__name__)


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
    Orquesta los 4 pasos del pipeline InSAR sobre un par Sentinel-1.

    Pasos:
        1. Co-registro de imágenes (reference + secondary)
        2. Generación del interferograma (diferencia de fase)
        3. Unwrapping de fase (snaphu)
        4. Geocodificación + exportación PNG
    """

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

        self.log_path = self.work_dir / "isce.log"
        self._file_log = self._setup_file_logger()

    # ── Pasos del pipeline ───────────────────────────────────────────────────

    def run(self) -> PipelineResult:
        log.info("[%s] Iniciando pipeline InSAR", self.job_id)
        try:
            self._step_coregister()
            ifg_path = self._step_interferogram()
            unw_path = self._step_unwrap(ifg_path)
            result   = self._step_geocode_and_export(unw_path)
            log.info("[%s] Pipeline completado", self.job_id)
            return result
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(f"Error inesperado en pipeline: {e}") from e

    def _step_coregister(self):
        """
        Paso 1: Co-registro de las dos imágenes Sentinel-1.
        Usa topsApp.py de ISCE2 con los SLC de entrada.
        """
        log.info("[%s] Paso 1: co-registro", self.job_id)

        config = self._write_topsapp_xml()
        self._run_isce_command(
            ["topsApp.py", str(config), "--end=preprocess"],
            step_name="coregister"
        )

    def _step_interferogram(self) -> Path:
        """
        Paso 2: Generación del interferograma (diferencia de fase compleja).
        Continúa topsApp.py hasta el paso del interferograma.
        """
        log.info("[%s] Paso 2: interferograma", self.job_id)

        config = self.work_dir / "topsApp.xml"
        self._run_isce_command(
            ["topsApp.py", str(config), "--start=computeBaselines", "--end=filter"],
            step_name="interferogram"
        )

        ifg_path = self.work_dir / "merged" / "filt_topophase.flat"
        if not ifg_path.exists():
            raise PipelineError(f"Interferograma no generado: {ifg_path}")
        return ifg_path

    def _step_unwrap(self, ifg_path: Path) -> Path:
        """
        Paso 3: Unwrapping de fase con SNAPHU.
        Convierte la fase envuelta [-π, π] a fase continua.
        """
        log.info("[%s] Paso 3: unwrapping", self.job_id)

        self._run_isce_command(
            ["topsApp.py", str(self.work_dir / "topsApp.xml"), "--start=unwrap", "--end=unwrap"],
            step_name="unwrap"
        )

        unw_path = self.work_dir / "merged" / "filt_topophase.unw"
        if not unw_path.exists():
            raise PipelineError(f"Unwrapping no generado: {unw_path}")
        return unw_path

    def _step_geocode_and_export(self, unw_path: Path) -> PipelineResult:
        """
        Paso 4: Geocodificación + exportación como PNG con colormap de deformación.
        """
        log.info("[%s] Paso 4: geocodificación y exportación", self.job_id)

        # Geocodificar
        self._run_isce_command(
            ["topsApp.py", str(self.work_dir / "topsApp.xml"), "--start=geocode", "--end=geocode"],
            step_name="geocode"
        )

        geo_path = self.work_dir / "merged" / "filt_topophase.unw.geo"
        if not geo_path.exists():
            log.warning("Geocodificado no encontrado, usando unwrapped directamente")
            geo_path = unw_path

        # Leer datos de fase y generar PNG
        phase_data, coherence = self._read_phase_and_coherence(geo_path)
        output_png = self._export_png(phase_data)

        # Bounding box (placeholder hasta tener .xml de geocodificado real)
        bbox_wkt = self._extract_bbox_wkt()

        return PipelineResult(
            output_image=output_png,
            mean_coherence=float(coherence),
            bbox_wkt=bbox_wkt,
            processed_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _write_topsapp_xml(self) -> Path:
        """Genera el archivo de configuración topsApp.xml para este par de imágenes."""
        xml_path = self.work_dir / "topsApp.xml"
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<topsApp>
  <component name="topsinsar">
    <property name="Sensor name">SENTINEL1</property>
    <component name="reference">
      <property name="safe">[ "{self.reference}" ]</property>
      <property name="output directory">reference</property>
    </component>
    <component name="secondary">
      <property name="safe">[ "{self.secondary}" ]</property>
      <property name="output directory">secondary</property>
    </component>
    <property name="working directory">{self.work_dir}</property>
    <property name="do unwrap">True</property>
    <property name="unwrapper name">snaphu</property>
    <property name="do geocode">True</property>
  </component>
</topsApp>
"""
        xml_path.write_text(content)
        return xml_path

    def _run_isce_command(self, cmd: list, step_name: str):
        """Ejecuta un comando de ISCE2 y loguea stdout/stderr."""
        log.info("[%s] Ejecutando: %s", self.job_id, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.work_dir),
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hora máximo por paso
            )
            with open(self.log_path, "a") as f:
                f.write(f"\n=== {step_name} ===\n")
                f.write(result.stdout)
                if result.stderr:
                    f.write(result.stderr)

            if result.returncode != 0:
                raise PipelineError(
                    f"Falló {step_name} (exit {result.returncode}):\n{result.stderr[-500:]}"
                )
        except subprocess.TimeoutExpired:
            raise PipelineError(f"Timeout en paso: {step_name}")

    def _read_phase_and_coherence(self, geo_path: Path):
        """
        Lee el archivo .unw.geo (formato BIL de ISCE2).
        Band 1 = coherencia, Band 2 = fase unwrapped.
        """
        try:
            import isce
            from isceobj.Image.Image import Image
            img = Image()
            img.load(str(geo_path) + ".xml")
            mm = np.memmap(
                str(geo_path),
                dtype=np.float32,
                mode="r",
                shape=(img.length, img.width * 2)
            )
            coherence = mm[:, 0::2]
            phase     = mm[:, 1::2]
        except Exception:
            # Fallback: leer como archivo binario plano
            log.warning("Usando lectura fallback de fase")
            raw = np.fromfile(str(geo_path), dtype=np.float32)
            half = len(raw) // 2
            coherence = raw[:half].reshape(-1, 1)
            phase     = raw[half:].reshape(-1, 1)

        # Máscarar píxeles de baja coherencia
        mask = coherence > 0.3
        phase_masked = np.where(mask, phase, np.nan)
        mean_coh = float(np.nanmean(coherence))
        return phase_masked, mean_coh

    def _export_png(self, phase_data: np.ndarray) -> Path:
        """
        Exporta el mapa de deformación como PNG.
        Convierte fase [rad] a deformación [cm] usando λ Sentinel-1 = 5.54 cm.
        """
        output_path = self.output_dir / f"deformation_{self.job_id}.png"

        # Fase → deformación en cm  (d = φ · λ / (4π))
        LAMBDA_CM = 5.54
        deformation = phase_data * LAMBDA_CM / (4 * np.pi)

        # Centrar en cero y recortar a percentil 99 para mejor visualización
        vmax = np.nanpercentile(np.abs(deformation), 99)
        vmin = -vmax

        fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
        im = ax.imshow(
            deformation,
            cmap="RdBu_r",
            vmin=vmin,
            vmax=vmax,
            interpolation="nearest",
        )
        cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
        cbar.set_label("Deformación (cm)", fontsize=11)
        ax.set_title(f"Mapa de deformación — Job {self.job_id[:8]}", fontsize=13)
        ax.axis("off")
        plt.tight_layout()
        plt.savefig(str(output_path), format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)

        log.info("[%s] PNG guardado: %s", self.job_id, output_path)
        return output_path

    def _extract_bbox_wkt(self) -> str:
        """
        Extrae el bounding box del área procesada en formato WKT.
        Lee los metadatos del geocodificado de ISCE2.
        """
        try:
            geo_xml = self.work_dir / "merged" / "filt_topophase.unw.geo.xml"
            if geo_xml.exists():
                import xml.etree.ElementTree as ET
                tree = ET.parse(str(geo_xml))
                root = tree.getroot()
                lat1 = float(root.findtext(".//property[@name='minimum latitude']/value", "0"))
                lat2 = float(root.findtext(".//property[@name='maximum latitude']/value", "0"))
                lon1 = float(root.findtext(".//property[@name='minimum longitude']/value", "0"))
                lon2 = float(root.findtext(".//property[@name='maximum longitude']/value", "0"))
                return (
                    f"POLYGON(({lon1} {lat1}, {lon2} {lat1}, "
                    f"{lon2} {lat2}, {lon1} {lat2}, {lon1} {lat1}))"
                )
        except Exception as e:
            log.warning("No se pudo extraer bbox: %s", e)
        return "POLYGON((0 0, 0 0, 0 0, 0 0, 0 0))"

    def _setup_file_logger(self) -> logging.FileHandler:
        handler = logging.FileHandler(str(self.log_path))
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        return handler