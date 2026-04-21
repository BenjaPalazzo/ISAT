from config import logger


# ──────────────────────────────────────────────
# CONSULTAS A LA API  (stubs — reemplazar)
# ──────────────────────────────────────────────

async def consultar_imagenes(
    lat: float,
    lon: float,
    fecha_inicio: str,
    fecha_fin: str,
    delta: float = 0.01,
) -> dict:
    """
    TODO: reemplazar con llamada real a la API de imágenes satelitales.
    """
    logger.info(f"Consultando imágenes: lat={lat} lon={lon} {fecha_inicio} → {fecha_fin}")
    return {
        "azimuth_looks": None,
        "connections": None,
        "path": None,
        "range_looks": None,
        "sensor": None,
        "workflow": None,
        "east":  lon + delta,
        "north": lat + delta,
        "south": lat - delta,
        "west":  lon - delta,
        "start": fecha_inicio,
        "end":   fecha_fin,
    }



async def consultar_deformacion(
    lat: float,
    lon: float,
    fecha_inicio: str,
    fecha_fin: str,
    delta: float = 0.01,
) -> dict:
    """
    TODO: reemplazar con llamada real a HyP3 / API propia / etc.
    """
    logger.info(f"Consultando deformación: lat={lat} lon={lon} {fecha_inicio} → {fecha_fin}")
    return {
        "azimuth_looks": None,
        "connections": None,
        "path": None,
        "range_looks": None,
        "sensor": None,
        "workflow": None,
        "east":  lon + delta,
        "north": lat + delta,
        "south": lat - delta,
        "west":  lon - delta,
        "start": fecha_inicio,
        "end":   fecha_fin,
    }