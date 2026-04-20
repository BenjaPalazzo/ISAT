import re
import datetime
import json
import logging
import httpx
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# ESTADOS del ConversationHandler
# ──────────────────────────────────────────────
ESPERANDO_UBICACION = 1

# ──────────────────────────────────────────────
# BACKEND STUB  (reemplazar con llamada real)
# ──────────────────────────────────────────────
async def consultar_imagenes(lat: float, lon: float, delta: float = 0.01) -> dict:
    """
    TODO: reemplazar con llamada real a la API de imágenes satelitales.
    """
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
        "end": "",
        "start": datetime.datetime.now().strftime("%Y-%m-%d"),
    }


async def consultar_deformacion(lat: float, lon: float, delta: float = 0.01) -> dict:
    """
    TODO: reemplazar con llamada real a HyP3 / API propia / etc.
    """
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
        "end": "",
        "start": datetime.datetime.now().strftime("%Y-%m-%d"),
    }


# ──────────────────────────────────────────────
# RESOLVER URL ACORTADA
# ──────────────────────────────────────────────
def resolver_url_corta(url: str) -> str:
    """Sigue redirects y devuelve la URL final expandida."""
    try:
        with httpx.Client(follow_redirects=True, timeout=5) as client:
            response = client.head(url)
            return str(response.url)
    except Exception as e:
        logger.warning(f"No se pudo resolver la URL '{url}': {e}")
        return url  # si falla, devuelve la original


# ──────────────────────────────────────────────
# PARSER DE UBICACIÓN DESDE TEXTO
# ──────────────────────────────────────────────
def parsear_ubicacion_texto(texto: str) -> tuple[float, float] | None:
    """
    Intenta extraer (lat, lon) de:
    - Google Maps: ?q=lat,lon  |  ?ll=lat,lon  |  /@lat,lon  |  !3dlat!4dlon
    - OpenStreetMap: #map=z/lat/lon
    - Coordenadas crudas: "-32.89, -68.84" o "-32.89 -68.84"
    """
    # Google Maps: ?q=lat,lon o ?ll=lat,lon
    m = re.search(r"[?&](?:q|ll)=(-?\d+\.?\d*),(-?\d+\.?\d*)", texto)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Google Maps: /@lat,lon
    m = re.search(r"/@(-?\d+\.?\d*),(-?\d+\.?\d*)", texto)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Google Maps: !3dlat!4dlon (formato de URLs largas de lugares)
    m = re.search(r"!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)", texto)
    if m:
        return float(m.group(1)), float(m.group(2))

    # OpenStreetMap: #map=z/lat/lon
    m = re.search(r"#map=\d+/(-?\d+\.?\d*)/(-?\d+\.?\d*)", texto)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Coordenadas crudas: "-32.89, -68.84" o "-32.89 -68.84"
    m = re.fullmatch(r"\s*(-?\d+\.?\d*)[,\s]+(-?\d+\.?\d*)\s*", texto)
    if m:
        return float(m.group(1)), float(m.group(2))

    return None


# ──────────────────────────────────────────────
# LÓGICA COMPARTIDA DE PROCESAMIENTO
# ──────────────────────────────────────────────
async def _procesar_ubicacion(lat: float, lon: float, modo: str, update: Update):
    """Llama a la API correspondiente y responde con el resultado."""
    await update.message.reply_text(
        f"📍 Ubicación recibida: `{lat}, {lon}`\n⏳ Procesando solicitud, aguardá un momento...",
        parse_mode="Markdown",
    )

    if modo == "imagenes":
        resultado = await consultar_imagenes(lat, lon)
        titulo = "📷 *Resultado — Imágenes SAR*"
    else:
        resultado = await consultar_deformacion(lat, lon)
        titulo = "📉 *Resultado — Deformación del terreno*"

    respuesta = (
        f"{titulo}\n\n"
        f"```json\n{json.dumps(resultado, indent=2, ensure_ascii=False)}\n```"
    )
    await update.message.reply_text(respuesta, parse_mode="Markdown")


# ──────────────────────────────────────────────
# HANDLERS
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "👋 *Bienvenido al bot satelital del ISAT*\n\n"
        "Usá los siguientes comandos:\n"
        "📷 /imagenes    → Solicitar imágenes SAR de una zona\n"
        "📉 /deformacion → Analizar deformación del terreno\n"
        "ℹ️ /ayuda        → Ver esta ayuda"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ── /imagenes ──
async def cmd_imagenes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["modo"] = "imagenes"
    await update.message.reply_text(
        "📷 *Solicitud de imágenes SAR*\n\n"
        "Enviá la ubicación de la zona de interés. Podés usar:\n"
        "• Un 📍 *pin de Telegram*\n"
        "• Un link de *Google Maps* o *OpenStreetMap*\n"
        "• Coordenadas directas: `-32.89, -68.84`\n\n"
        "Usá /cancelar para salir.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ESPERANDO_UBICACION


# ── /deformacion ──
async def cmd_deformacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["modo"] = "deformacion"
    await update.message.reply_text(
        "📉 *Análisis de deformación del terreno*\n\n"
        "Enviá la ubicación de la zona de interés. Podés usar:\n"
        "• Un 📍 *pin de Telegram*\n"
        "• Un link de *Google Maps* o *OpenStreetMap*\n"
        "• Coordenadas directas: `-32.89, -68.84`\n\n"
        "Usá /cancelar para salir.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ESPERANDO_UBICACION


# ── Recibir ubicación nativa (pin de Telegram) ──
async def recibir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = update.message.location
    lat = location.latitude
    lon = location.longitude

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        await update.message.reply_text("❌ Coordenadas inválidas. Intentá de nuevo.")
        return ESPERANDO_UBICACION

    modo = context.user_data.get("modo", "imagenes")
    await _procesar_ubicacion(lat, lon, modo, update)
    return ConversationHandler.END


# ── Recibir ubicación desde texto (links o coordenadas) ──
async def recibir_ubicacion_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text

    # Si el mensaje contiene una URL, resolver posibles redirects (ej: maps.app.goo.gl)
    url_match = re.search(r"https?://\S+", texto)
    if url_match:
        url_original = url_match.group()
        url_resuelta = resolver_url_corta(url_original)
        logger.info(f"URL resuelta: {url_original} → {url_resuelta}")
        texto = texto.replace(url_original, url_resuelta)

    resultado = parsear_ubicacion_texto(texto)

    if resultado is None:
        await update.message.reply_text(
            "❌ No pude interpretar la ubicación. Podés enviar:\n"
            "• Un 📍 pin de Telegram\n"
            "• Un link de Google Maps o OpenStreetMap\n"
            "• Coordenadas: `-32.89, -68.84`",
            parse_mode="Markdown",
        )
        return ESPERANDO_UBICACION

    lat, lon = resultado

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        await update.message.reply_text("❌ Coordenadas fuera de rango. Intentá de nuevo.")
        return ESPERANDO_UBICACION

    modo = context.user_data.get("modo", "imagenes")
    await _procesar_ubicacion(lat, lon, modo, update)
    return ConversationHandler.END


# ── /cancelar ──
async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operación cancelada. Usá /imagenes o /deformacion para empezar de nuevo."
    )
    return ConversationHandler.END


# ── Mensajes de texto fuera de flujo ──
async def mensaje_generico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 *Bot satelital ISAT*\n\n"
        "Usá /imagenes o /deformacion para comenzar.",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(os.getenv("TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("imagenes",    cmd_imagenes),
            CommandHandler("deformacion", cmd_deformacion),
        ],
        states={
            ESPERANDO_UBICACION: [
                MessageHandler(filters.LOCATION, recibir_ubicacion),
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ubicacion_texto),
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", cancelar),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_generico))

    logger.info("Bot iniciado ✅")
    app.run_polling()


if __name__ == "__main__":
    main()