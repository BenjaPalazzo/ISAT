"""
mock_pipeline.py — Simula el pipeline ISCE2 sin necesitar imágenes reales.
Genera un mapa de deformación sintético realista (subsidencia gaussiana + ruido).
Tiene la misma interfaz que pipeline.py → el api_server.py no necesita cambios.
"""

import logging
import time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


@dataclass
class PipelineResult:
    output_image:   Path
    mean_coherence: float
    bbox_wkt:       str
    processed_at:   str


class ISCEPipeline:
    """
    Mock del pipeline ISCE2.
    Genera datos sintéticos que simulan un evento de subsidencia real.
    """

    def __init__(self, reference_image, secondary_image, work_dir, output_dir, job_id):
        self.reference  = Path(reference_image)
        self.secondary  = Path(secondary_image)
        self.work_dir   = Path(work_dir)
        self.output_dir = Path(output_dir)
        self.job_id     = job_id
        self.log_path   = self.work_dir / "isce.log"

    def run(self) -> PipelineResult:
        log.info("[MOCK][%s] Iniciando pipeline simulado", self.job_id)

        self._simulate_step("Co-registro de imágenes Sentinel-1",    delay=0.5)
        self._simulate_step("Generación de interferograma",           delay=0.5)
        self._simulate_step("Unwrapping de fase (SNAPHU)",            delay=0.5)
        self._simulate_step("Geocodificación",                        delay=0.3)

        phase_data, coherence = self._generate_synthetic_deformation()
        output_png = self._export_png(phase_data)

        print("Imagen generada en:", output_png)  # 👈 ACÁ


        return PipelineResult(
            output_image   = output_png,
            mean_coherence = float(coherence),
            bbox_wkt       = "POLYGON((-69.5 -32.8, -68.5 -32.8, -68.5 -33.5, -69.5 -33.5, -69.5 -32.8))",
            processed_at   = datetime.now(timezone.utc).isoformat(),
        )
    

    def _simulate_step(self, name: str, delay: float):
        log.info("[MOCK][%s] %s...", self.job_id, name)
        time.sleep(delay)

    def _generate_synthetic_deformation(self):
        """
        Genera un campo de deformación sintético realista:
        - Zona de subsidencia central (ej: extracción de agua subterránea)
        - Zona de uplift secundaria
        - Ruido de fase realista
        - Coherencia variable (baja en zonas de vegetación densa)
        """
        rows, cols = 400, 500
        y = np.linspace(-1, 1, rows)
        x = np.linspace(-1, 1, cols)
        X, Y = np.meshgrid(x, y)

        # Subsidencia principal (forma gaussiana, -8 cm en el centro)
        subsidence = -8.0 * np.exp(-(X**2 + Y**2) / 0.15)

        # Uplift secundario (falla lateral)
        uplift = 3.5 * np.exp(-((X - 0.6)**2 + (Y + 0.3)**2) / 0.08)

        # Gradiente orbital residual (muy común en InSAR real)
        orbital_ramp = 0.8 * X - 0.4 * Y

        # Ruido de fase (simula decorrelación)
        np.random.seed(42)
        noise = np.random.normal(0, 0.4, (rows, cols))
        # Suavizar el ruido con convolución simple (sin scipy)
        pad = 4
        noise_padded = np.pad(noise, pad, mode="reflect")
        from numpy.lib.stride_tricks import sliding_window_view
        windows = sliding_window_view(noise_padded, (9, 9))
        noise = windows.mean(axis=(-1, -2))

        deformation = subsidence + uplift + orbital_ramp + noise

        # Coherencia: alta en zonas urbanas/áridas, baja en vegetación
        coherence = 0.75 + 0.2 * np.exp(-(X**2 + Y**2) / 0.5)
        coherence += np.random.normal(0, 0.05, (rows, cols))
        coherence = np.clip(coherence, 0.1, 0.99)

        # Máscara de baja coherencia (simula cuerpos de agua)
        water_mask = (X + 0.8)**2 + (Y - 0.7)**2 < 0.04
        deformation[water_mask] = np.nan
        coherence[water_mask] = 0.0

        mean_coh = float(np.nanmean(coherence))
        return deformation, mean_coh

    def _export_png(self, deformation: np.ndarray) -> Path:
        output_path = self.output_dir / f"deformation_{self.job_id}.png"

        vmax = np.nanpercentile(np.abs(deformation), 98)
        vmin = -vmax

        fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=130)
        fig.patch.set_facecolor("#0f0f0f")

        # Panel izquierdo: mapa de deformación
        ax1 = axes[0]
        im = ax1.imshow(deformation, cmap="RdBu_r", vmin=vmin, vmax=vmax,
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

        # Anotar mín/máx
        min_val = np.nanmin(deformation)
        max_val = np.nanmax(deformation)
        ax1.set_xlabel(
            f"Min: {min_val:.1f} cm  |  Max: {max_val:.1f} cm",
            color="#aaa", fontsize=9
        )

        # Panel derecho: histograma de deformación
        ax2 = axes[1]
        valid = deformation[~np.isnan(deformation)].flatten()
        ax2.hist(valid, bins=60, color="#4a90d9", edgecolor="none", alpha=0.85)
        ax2.axvline(0, color="white", linewidth=1, linestyle="--", alpha=0.6)
        ax2.set_facecolor("#1a1a2e")
        ax2.set_title("Distribución de deformación", color="white", fontsize=12, pad=10)
        ax2.set_xlabel("Deformación (cm)", color="white", fontsize=10)
        ax2.set_ylabel("Número de píxeles", color="white", fontsize=10)
        ax2.tick_params(colors="white")
        for spine in ax2.spines.values():
            spine.set_edgecolor("#444")

        fig.suptitle(
            f"[MOCK] Job {self.job_id[:8]} — Sentinel-1 InSAR",
            color="white", fontsize=13, y=1.01
        )
        plt.tight_layout()
        plt.savefig(str(output_path), format="png", bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)

        log.info("[MOCK][%s] PNG generado: %s", self.job_id, output_path)
        return output_path
    


