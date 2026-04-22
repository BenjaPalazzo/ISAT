"""
demo_mendoza.py — Simulación InSAR ultra-realista sobre Mendoza, Argentina
Genera las 4 salidas reales de ISCE2:
  1. Amplitud SAR (imagen de backscatter)
  2. Interferograma envuelto (fringes de color)
  3. Mapa de coherencia
  4. Mapa de deformación final (fase unwrapped → cm)

Simula un sismo Mw 5.8 en la falla Precordillera (~20 km al oeste de Mendoza).
Zona: -33.0°S a -32.4°S / -69.4°W a -68.6°W
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.colors import LinearSegmentedColormap
from pathlib import Path

# ── Parámetros del área de estudio ────────────────────────────────────────────

AREA = dict(
    lat_min=-33.0, lat_max=-32.4,
    lon_min=-69.4, lon_max=-68.6,
    name="Precordillera mendocina",
)

SENTINEL = dict(
    wavelength_cm = 5.5465,       # C-band λ
    incidence_deg = 60.0,         # ángulo de incidencia típico IW
    heading_deg   = -168.0,       # órbita descendente
    baseline_m    =  50,        # baseline perpendicular
    temporal_days = 700,           # separación temporal
)

ROWS, COLS = 600, 800
OUTDIR = Path("/tmp/demo_mendoza")
OUTDIR.mkdir(parents=True, exist_ok=True)

# ── Grilla geográfica ─────────────────────────────────────────────────────────

lats = np.linspace(AREA["lat_min"], AREA["lat_max"], ROWS)
lons = np.linspace(AREA["lon_min"], AREA["lon_max"], COLS)
LON, LAT = np.meshgrid(lons, lats)

# Coordenadas normalizadas centradas
X = (LON - LON.mean()) / (LON.max() - LON.min()) * 2
Y = (LAT - LAT.mean()) / (LAT.max() - LAT.min()) * 2

# ── 1. DEM sintético (topografía andina) ─────────────────────────────────────

def make_dem():
    """
    Genera un DEM realista para la zona Precordillera-Piedemonte mendocino.
    Oeste: cordillera alta (3000-5000m), Este: piedemonte y llanura (<1500m).
    """
    rng = np.random.default_rng(seed=77)

    # Gradiente principal O→E (Andes al oeste)
    base = 3200 * np.exp(2.5 * (X - 0.3)) + 800
    base = np.clip(base, 500, 5500)

    # Cadenas montañosas paralelas (strikes N-S típicos de Precordillera)
    ridges = (
        400 * np.exp(-((X + 0.8)**2) / 0.03) +
        600 * np.exp(-((X + 0.4)**2) / 0.04) +
        350 * np.exp(-((X - 0.1)**2) / 0.025) +
        250 * np.exp(-((X - 0.5)**2) / 0.02)
    )

    # Valles fluviales (Río Mendoza, Río Tunuyán)
    rio_mendoza = -180 * np.exp(-((Y + 0.2)**2 + (X - 0.3)**2) / 0.006)
    rio_tunuyan = -120 * np.exp(-((Y - 0.5)**2 + (X - 0.1)**2) / 0.008)

    # Ruido fractal (rugosidad realista)
    noise = np.zeros((ROWS, COLS))
    for scale, amp in [(0.05, 300), (0.02, 120), (0.008, 60), (0.003, 25)]:
        freq = int(1 / scale)
        sr = max(2, ROWS // freq)
        sc = max(2, COLS // freq)
        small = rng.normal(0, amp, (sr, sc))
        from numpy import kron
        zoomed = kron(small, np.ones((freq, freq)))
        zr, zc = zoomed.shape
        if zr < ROWS or zc < COLS:
            padded = np.zeros((ROWS, COLS))
            padded[:min(zr,ROWS), :min(zc,COLS)] = zoomed[:min(zr,ROWS), :min(zc,COLS)]
            zoomed = padded
        noise += zoomed[:ROWS, :COLS]

    dem = base + ridges + rio_mendoza + rio_tunuyan + noise
    return np.clip(dem, 400, 6200)


dem = make_dem()

# ── 2. Mapa de coherencia realista ────────────────────────────────────────────

def make_coherence(dem):
    """
    Coherencia alta: zona urbana Mendoza, pedregal, roca desnuda.
    Coherencia baja: viñedos/agricultura (decorrelación temporal), agua.
    """
    rng = np.random.default_rng(seed=42)
    coh = np.ones((ROWS, COLS)) * 0.75

    # Ciudad de Mendoza (alta coherencia ~0.92)
    ciudad = np.exp(-((LON - (-68.83))**2 + (LAT - (-32.89))**2) / 0.004)
    coh += 0.18 * ciudad

    # Zona agrícola / viñedos al este (~0.35 coherencia)
    agro_mask = LON > -68.95
    agro_coh  = 0.35 + 0.15 * rng.random((ROWS, COLS))
    coh = np.where(agro_mask, agro_coh, coh)

    # Alta montaña: roca desnuda, alta coherencia
    alta_montana = dem > 3500
    coh = np.where(alta_montana, np.clip(coh + 0.10, 0, 0.97), coh)

    # Glaciares/nieve (baja coherencia)
    glaciar = dem > 4800
    coh = np.where(glaciar, 0.25 + 0.1 * rng.random((ROWS, COLS)), coh)

    # Ríos (muy baja coherencia)
    rio1 = np.exp(-((Y + 0.2)**2 + (X - 0.3)**2) / 0.001) > 0.3
    rio2 = np.exp(-((Y - 0.5)**2 + (X - 0.1)**2) / 0.001) > 0.25
    coh  = np.where(rio1 | rio2, 0.10 + 0.08 * rng.random((ROWS, COLS)), coh)

    # Ruido espacial suave
    noise = rng.normal(0, 0.04, (ROWS, COLS))
    pad   = 6
    noise_padded = np.pad(noise, pad, mode="reflect")
    from numpy.lib.stride_tricks import sliding_window_view
    noise = sliding_window_view(noise_padded, (13, 13)).mean(axis=(-1, -2))
    coh  += noise

    return np.clip(coh, 0.05, 0.97)


coherence = make_coherence(dem)

# ── 3. Amplitud SAR (backscatter) ─────────────────────────────────────────────

def make_amplitude(dem, coherence):
    """
    Simula la imagen de amplitud SAR de Sentinel-1.
    Alta amplitud: zonas urbanas (doble rebote), pendientes orientadas al radar.
    """
    rng = np.random.default_rng(seed=11)

    # Gradiente topográfico (layover/shadow en pendientes)
    ddem_dx = np.gradient(dem, axis=1)
    ddem_dy = np.gradient(dem, axis=0)
    slope   = np.sqrt(ddem_dx**2 + ddem_dy**2)

    base_amp = 0.3 + 0.4 * (slope / slope.max())

    # Ciudad: alta amplitud por reflexión urbana
    ciudad = np.exp(-((LON - (-68.83))**2 + (LAT - (-32.89))**2) / 0.003)
    base_amp += 0.45 * ciudad

    # Pedregal/roca: amplitud media-alta
    roca  = (dem > 2000) & (dem < 4500)
    base_amp = np.where(roca, base_amp + 0.15, base_amp)

    # Speckle SAR (distribución Rayleigh)
    speckle = rng.rayleigh(scale=0.85, size=(ROWS, COLS))
    amp     = base_amp * speckle
    amp     = np.clip(amp, 0.01, 5.0)

    # Convertir a dB con clip
    amp_db = 10 * np.log10(amp + 0.01)
    return np.clip(amp_db, -20, 10)


amplitude = make_amplitude(dem, coherence)

# ── 4. Deformación: sismo Mw 5.8 en Falla Precordillera ──────────────────────

def make_deformation_sismo():
    """
    Modelo de Okada simplificado para un sismo Mw 5.8.
    Falla inversa en la Precordillera, hiperentro ~12 km.
    Deformación LOS máxima ~4.5 cm (subsidencia + uplift).
    """
    # Epicentro: falla Precordillera (~20 km al oeste de Mendoza)
    epi_lon, epi_lat = -69.15, -32.72

    R = np.sqrt((LON - epi_lon)**2 + (LAT - epi_lat)**2)

    # Lóbulo de subsidencia (hanging wall)
    subsidencia = -4.5 * np.exp(-R**2 / 0.018)

    # Lóbulo de uplift (foot wall) desplazado ~15 km al este
    uplift = 2.2 * np.exp(-((LON - (epi_lon + 0.15))**2 +
                             (LAT - (epi_lat - 0.05))**2) / 0.010)

    # Gradiente de deformación en la traza de falla (discontinuidad suave)
    fault_trace = 0.8 * np.tanh((LON - epi_lon + 0.05) / 0.04)

    deformation = subsidencia + uplift + fault_trace
    return deformation  # en cm


deformation_cm = make_deformation_sismo()

# ── 5. Fase interferométrica ──────────────────────────────────────────────────

def deformation_to_phase(def_cm):
    """Convierte deformación LOS [cm] → fase [rad] usando λ Sentinel-1."""
    lam = SENTINEL["wavelength_cm"]
    return (4 * np.pi / lam) * def_cm


# Fase topográfica residual (topo incompleta, baseline ≠ 0)
def topo_phase(dem):
    lam  = SENTINEL["wavelength_cm"]
    B    = SENTINEL["baseline_m"]
    inc  = np.radians(SENTINEL["incidence_deg"])
    R    = 880_000  # distancia slant típica Sentinel-1 [cm]
    return (4 * np.pi * B * dem * 100) / (lam * R * np.sin(inc))


# Ruido atmosférico (APS — Atmospheric Phase Screen)
def atm_noise():
    rng = np.random.default_rng(seed=99)
    noise = rng.normal(0, 0.3, (ROWS // 8, COLS // 8))
    from numpy import kron
    upsampled = kron(noise, np.ones((8, 8)))[:ROWS, :COLS]
    pad = 10
    padded = np.pad(upsampled, pad, mode="reflect")
    from numpy.lib.stride_tricks import sliding_window_view
    return sliding_window_view(padded, (21, 21)).mean(axis=(-1, -2)) * 1.5


phase_signal = deformation_to_phase(deformation_cm)
phase_topo   = topo_phase(dem) * 0.08   # residuo topográfico reducido
phase_atm    = atm_noise()
phase_noise  = np.random.default_rng(55).normal(0, 0.2, (ROWS, COLS))

# Enmascarar por coherencia
coh_mask = coherence < 0.3
phase_total = phase_signal + phase_topo + phase_atm + phase_noise
phase_total[coh_mask] = np.nan

# Fase envuelta [-π, π]
phase_wrapped = np.angle(np.exp(1j * phase_total))

# ── 6. Colormaps ──────────────────────────────────────────────────────────────

# Colormap interferograma (ciclo de fringes estilo SNAPHU)
colors_ifg = [
    (0.00, "#1a1aff"),  # azul profundo
    (0.17, "#00ccff"),  # cyan
    (0.33, "#00ff88"),  # verde
    (0.50, "#ffff00"),  # amarillo
    (0.67, "#ff8800"),  # naranja
    (0.83, "#ff0044"),  # rojo
    (1.00, "#1a1aff"),  # cierra el ciclo
]
cmap_ifg = LinearSegmentedColormap.from_list(
    "interferogram",
    [(v, c) for v, c in colors_ifg],
    N=512
)

cmap_coh  = plt.cm.gray
cmap_amp  = plt.cm.gray
cmap_def  = plt.cm.RdBu_r

# ── 7. Figura final ───────────────────────────────────────────────────────────

def plot_results():
    fig = plt.figure(figsize=(18, 12), dpi=130)
    fig.patch.set_facecolor("#0d0d0d")

    gs = fig.add_gridspec(2, 3, hspace=0.35, wspace=0.25,
                          left=0.05, right=0.95, top=0.90, bottom=0.06)

    extent = [AREA["lon_min"], AREA["lon_max"], AREA["lat_min"], AREA["lat_max"]]

    def styled_ax(ax, title):
        ax.set_facecolor("#111")
        ax.set_title(title, color="white", fontsize=11, pad=8, fontweight="500")
        ax.tick_params(colors="#888", labelsize=7)
        for sp in ax.spines.values():
            sp.set_edgecolor("#333")
        ax.set_xlabel("Longitud", color="#888", fontsize=8)
        ax.set_ylabel("Latitud", color="#888", fontsize=8)
        return ax

    def add_colorbar(fig, im, ax, label, fmt="%.1f"):
        cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03, format=fmt)
        cb.set_label(label, color="#aaa", fontsize=8)
        cb.ax.yaxis.set_tick_params(color="#666", labelsize=7)
        plt.setp(cb.ax.yaxis.get_ticklabels(), color="#aaa")
        return cb

    # Panel 1: Amplitud SAR
    ax1 = styled_ax(fig.add_subplot(gs[0, 0]), "Amplitud SAR — Referencia")
    im1 = ax1.imshow(amplitude, cmap=cmap_amp, extent=extent,
                     aspect="auto", vmin=-18, vmax=8, origin="upper")
    add_colorbar(fig, im1, ax1, "Backscatter (dB)")
    ax1.annotate("Mendoza", xy=(-68.83, -32.89), xytext=(-68.65, -32.78),
                 color="yellow", fontsize=8,
                 arrowprops=dict(arrowstyle="->", color="yellow", lw=0.8))

    # Panel 2: Interferograma envuelto
    ax2 = styled_ax(fig.add_subplot(gs[0, 1]), "Interferograma envuelto")
    phase_plot = np.where(np.isnan(phase_wrapped), np.nan, phase_wrapped)
    im2 = ax2.imshow(phase_plot, cmap=cmap_ifg, extent=extent,
                     aspect="auto", vmin=-np.pi, vmax=np.pi, origin="upper")
    add_colorbar(fig, im2, ax2, "Fase (rad)", fmt="%.2f")
    ax2.annotate("Epicentro\nMw 5.8", xy=(-69.15, -32.72),
                 xytext=(-69.35, -32.55),
                 color="white", fontsize=8, ha="center",
                 arrowprops=dict(arrowstyle="->", color="white", lw=0.8))

    # Panel 3: Coherencia
    ax3 = styled_ax(fig.add_subplot(gs[0, 2]), "Coherencia interferométrica")
    im3 = ax3.imshow(coherence, cmap=cmap_coh, extent=extent,
                     aspect="auto", vmin=0, vmax=1, origin="upper")
    add_colorbar(fig, im3, ax3, "Coherencia [0–1]", fmt="%.2f")

    # Panel 4: DEM
    ax4 = styled_ax(fig.add_subplot(gs[1, 0]), "Modelo de elevación (DEM)")
    cmap_dem = plt.cm.terrain
    im4 = ax4.imshow(dem, cmap=cmap_dem, extent=extent,
                     aspect="auto", vmin=400, vmax=5500, origin="upper")
    add_colorbar(fig, im4, ax4, "Elevación (m)", fmt="%d")

    # Panel 5: Deformación unwrapped
    vmax = np.nanpercentile(np.abs(deformation_cm), 99)
    ax5 = styled_ax(fig.add_subplot(gs[1, 1]), "Deformación LOS (unwrapped)")
    im5 = ax5.imshow(deformation_cm, cmap=cmap_def, extent=extent,
                     aspect="auto", vmin=-vmax, vmax=vmax, origin="upper")
    cb5 = add_colorbar(fig, im5, ax5, "Deformación (cm)")
    # Contornos de deformación
    cs = ax5.contour(lons, lats[::-1], np.flipud(deformation_cm),
                     levels=np.arange(-4, 4.5, 1), colors="white",
                     linewidths=0.4, alpha=0.4)
    ax5.clabel(cs, fmt="%.0f cm", fontsize=6, colors="white")

    # Panel 6: Estadísticas
    ax6 = fig.add_subplot(gs[1, 2])
    ax6.set_facecolor("#111")
    ax6.set_title("Estadísticas del procesamiento", color="white",
                  fontsize=11, pad=8, fontweight="500")
    for sp in ax6.spines.values():
        sp.set_edgecolor("#333")
    ax6.set_xticks([]); ax6.set_yticks([])

    stats = [
        ("Satélite",            "Sentinel-1A (C-band)"),
        ("Longitud de onda λ",  f"{SENTINEL['wavelength_cm']} cm"),
        ("Baseline perpendicular", f"{SENTINEL['baseline_m']} m"),
        ("Separación temporal", f"{SENTINEL['temporal_days']} días"),
        ("Ángulo de incidencia", f"{SENTINEL['incidence_deg']}°"),
        ("Área cubierta",       f"{AREA['name']}"),
        ("Coherencia media",    f"{np.nanmean(coherence):.3f}"),
        ("Deformación máx",     f"{np.nanmax(deformation_cm):.1f} cm"),
        ("Deformación mín",     f"{np.nanmin(deformation_cm):.1f} cm"),
        ("Píxeles válidos",
         f"{(~np.isnan(phase_wrapped)).sum() / phase_wrapped.size * 100:.1f}%"),
        ("Resolución grilla",   f"{ROWS} × {COLS} px"),
        ("Evento simulado",     "Sismo Mw 5.8 — Precordillera"),
    ]
    y0 = 0.96
    for label, val in stats:
        ax6.text(0.02, y0, label + ":", transform=ax6.transAxes,
                 color="#888", fontsize=8.5, va="top")
        ax6.text(0.55, y0, val, transform=ax6.transAxes,
                 color="#e0e0e0", fontsize=8.5, va="top", fontweight="500")
        y0 -= 0.076

    fig.suptitle(
        "Simulación InSAR — Precordillera Mendocina, Argentina\n"
        "Sentinel-1 | Falla inversa Precordillera | Sismo Mw 5.8 simulado",
        color="white", fontsize=14, y=0.97, fontweight="500"
    )

    out = OUTDIR / "interferograma_mendoza3.png"
    plt.savefig(str(out), format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor(), dpi=130)
    plt.close(fig)
    print(f"✓ Imagen guardada: {out}")
    return out


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time
    print("=" * 55)
    print("  InSAR Demo — Precordillera Mendocina")
    print("=" * 55)

    steps = [
        ("Generando DEM (topografía andina)",   lambda: None),
        ("Calculando coherencia",               lambda: None),
        ("Simulando backscatter SAR",           lambda: None),
        ("Modelando deformación sísmica",       lambda: None),
        ("Calculando fase interferométrica",    lambda: None),
        ("Renderizando figura final",           plot_results),
    ]

    for msg, fn in steps:
        print(f"  → {msg}...", end=" ", flush=True)
        t0 = time.time()
        fn()
        print(f"({time.time()-t0:.1f}s)")

    print()
    print(f"  Área:       {AREA['lat_min']}°S–{AREA['lat_max']}°S | "
          f"{AREA['lon_min']}°W–{AREA['lon_max']}°W")
    print(f"  Coherencia: {np.nanmean(coherence):.3f} media")
    print(f"  Deformación:{np.nanmin(deformation_cm):.1f} / "
          f"{np.nanmax(deformation_cm):.1f} cm (mín/máx)")
    print("=" * 55)