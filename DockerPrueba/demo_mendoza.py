#!/usr/bin/env python3

import os
import numpy as np
import struct

# ── Parámetros de la escena sintética ────────────────────────────────────────
WIDTH   = 200          # columnas (range)
LENGTH  = 200          # filas (azimuth)
N_IFGS  = 3            # interferogramas a generar
REF_DATE = "20230101"
DATES   = ["20230101", "20230201", "20230303", "20230402"]
BASE_DIR = "/data/copahue_stack"

# Pares de interferogramas (formato ISCE: date1_date2)
PAIRS = [
    (DATES[0], DATES[1]),
    (DATES[1], DATES[2]),
    (DATES[2], DATES[3]),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def write_isce_xml(path, width, length, dtype="FLOAT", bands=1):
    """Escribe el XML mínimo que MintPy necesita para leer un archivo ISCE."""
    xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<imageFile>
  <property name="WIDTH"><value>{width}</value></property>
  <property name="LENGTH"><value>{length}</value></property>
  <property name="NUMBER_BANDS"><value>{bands}</value></property>
  <property name="DATA_TYPE"><value>{dtype}</value></property>
  <property name="SCHEME"><value>BIL</value></property>
  <property name="FILE_NAME"><value>{os.path.basename(path)}</value></property>
</imageFile>
"""
    with open(path + ".xml", "w") as f:
        f.write(xml)


def write_binary(path, data, dtype=np.float32):
    """Escribe array numpy como binario big-endian (convención ISCE)."""
    data.astype(dtype).byteswap().tofile(path)


def synthetic_unw(pair_idx, width, length):
    """Fase desenvuelta sintética: señal suave + ruido leve."""
    x = np.linspace(0, 2 * np.pi, width)
    y = np.linspace(0, 2 * np.pi, length)
    xx, yy = np.meshgrid(x, y)
    signal = (pair_idx + 1) * 0.5 * np.sin(xx) * np.cos(yy)
    noise  = np.random.normal(0, 0.1, (length, width))
    return (signal + noise).astype(np.float32)


def synthetic_cor(width, length):
    """Coherencia sintética entre 0.4 y 0.95."""
    base = np.random.uniform(0.4, 0.95, (length, width))
    return base.astype(np.float32)


def synthetic_conncomp(width, length):
    """Componente conectada: todos en componente 1 (escena limpia)."""
    return np.ones((length, width), dtype=np.uint8)


# ── Estructura de directorios ─────────────────────────────────────────────────

def make_dirs():
    dirs = [
        f"{BASE_DIR}/merged/SLC/{REF_DATE}/referenceShelve",
        f"{BASE_DIR}/baselines",
        f"{BASE_DIR}/geom_reference",
    ]
    for pair in PAIRS:
        dirs.append(f"{BASE_DIR}/Igrams/{pair[0]}_{pair[1]}")
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    print(f"[OK] Directorios creados en {BASE_DIR}")


# ── Geometría ─────────────────────────────────────────────────────────────────

def write_geometry():
    geom_dir = f"{BASE_DIR}/geom_reference"

    # DEM sintético (altura ~1000 m con variación suave)
    hgt = 1000 + 200 * np.random.rand(LENGTH, WIDTH).astype(np.float32)
    write_binary(f"{geom_dir}/hgt.rdr", hgt)
    write_isce_xml(f"{geom_dir}/hgt.rdr", WIDTH, LENGTH)

    # Latitud (rango ~-37.5 a -37.0)
    lat_vals = np.linspace(-37.5, -37.0, LENGTH)
    lat = np.tile(lat_vals[:, None], (1, WIDTH)).astype(np.float32)
    write_binary(f"{geom_dir}/lat.rdr", lat)
    write_isce_xml(f"{geom_dir}/lat.rdr", WIDTH, LENGTH)

    # Longitud (rango ~-71.0 a -70.5)
    lon_vals = np.linspace(-71.0, -70.5, WIDTH)
    lon = np.tile(lon_vals[None, :], (LENGTH, 1)).astype(np.float32)
    write_binary(f"{geom_dir}/lon.rdr", lon)
    write_isce_xml(f"{geom_dir}/lon.rdr", WIDTH, LENGTH)

    # LOS (incidencia ~35°, azimuth ~-170°) — 2 bandas en el mismo archivo
    inc = np.full((LENGTH, WIDTH), 35.0, dtype=np.float32)
    az  = np.full((LENGTH, WIDTH), -170.0, dtype=np.float32)
    los = np.stack([inc, az], axis=0)          # shape (2, LENGTH, WIDTH)
    los.astype(np.float32).byteswap().tofile(f"{geom_dir}/los.rdr")
    write_isce_xml(f"{geom_dir}/los.rdr", WIDTH, LENGTH, bands=2)

    # Máscaras
    shadow = np.zeros((LENGTH, WIDTH), dtype=np.uint8)
    write_binary(f"{geom_dir}/shadowMask.rdr", shadow, dtype=np.uint8)
    write_isce_xml(f"{geom_dir}/shadowMask.rdr", WIDTH, LENGTH, dtype="BYTE")

    water = np.zeros((LENGTH, WIDTH), dtype=np.uint8)
    write_binary(f"{geom_dir}/waterMask.rdr", water, dtype=np.uint8)
    write_isce_xml(f"{geom_dir}/waterMask.rdr", WIDTH, LENGTH, dtype="BYTE")

    print("[OK] Geometría escrita")


# ── Metadatos de referencia (data.dat) ───────────────────────────────────────

def write_metadata():
    dat_path = f"{BASE_DIR}/merged/SLC/{REF_DATE}/referenceShelve/data.dat"
    meta = f"""
WIDTH = {WIDTH}
FILE_LENGTH = {LENGTH}
WAVELENGTH = 0.055465763
RANGE_PIXEL_SIZE = 2.329562
AZIMUTH_PIXEL_SIZE = 14.085
CENTER_LINE_UTC = 50000.0
STARTING_RANGE = 800000.0
HEADING = -169.5
ORBIT_DIRECTION = DESCENDING
PLATFORM = SENTINEL1
DATE = {REF_DATE}
"""
    with open(dat_path, "w") as f:
        f.write(meta)
    print(f"[OK] Metadatos escritos: {dat_path}")


# ── Baselines ─────────────────────────────────────────────────────────────────

def write_baselines():
    bdir = f"{BASE_DIR}/baselines"
    for i, (d1, d2) in enumerate(PAIRS):
        bline_dir = os.path.join(bdir, f"{d1}_{d2}")
        os.makedirs(bline_dir, exist_ok=True)
        bfile = os.path.join(bline_dir, f"{d1}_{d2}.txt")
        perp = (i + 1) * 30.0   # baseline perpendicular sintético
        with open(bfile, "w") as f:
            f.write(f"P_BASELINE_TOP_HDR = {perp:.4f}\n")
            f.write(f"P_BASELINE_BOTTOM_HDR = {perp + 0.5:.4f}\n")
    print(f"[OK] Baselines escritos")


# ── Interferogramas ───────────────────────────────────────────────────────────

def write_interferograms():
    for i, (d1, d2) in enumerate(PAIRS):
        igram_dir = f"{BASE_DIR}/Igrams/{d1}_{d2}"

        prefix = f"filt_{d1}_{d2}"

        # .unw — fase desenvuelta
        unw = synthetic_unw(i, WIDTH, LENGTH)
        unw_path = f"{igram_dir}/{prefix}.unw"
        write_binary(unw_path, unw)
        write_isce_xml(unw_path, WIDTH, LENGTH)

        # .cor — coherencia
        cor = synthetic_cor(WIDTH, LENGTH)
        cor_path = f"{igram_dir}/{prefix}.cor"
        write_binary(cor_path, cor)
        write_isce_xml(cor_path, WIDTH, LENGTH)

        # .unw.conncomp — componente conectada
        cc = synthetic_conncomp(WIDTH, LENGTH)
        cc_path = f"{igram_dir}/{prefix}.unw.conncomp"
        write_binary(cc_path, cc, dtype=np.uint8)
        write_isce_xml(cc_path, WIDTH, LENGTH, dtype="BYTE")

        print(f"[OK] Interferograma {d1}_{d2} escrito")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)
    print("=== Generando datos sintéticos tipo ISCE ===")
    make_dirs()
    write_geometry()
    write_metadata()
    write_baselines()
    write_interferograms()
    print("\n=== Listo. Stack en:", BASE_DIR, "===")