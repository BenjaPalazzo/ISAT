import datetime
import json
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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
# HANDLERS
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida."""
    texto = (
        "👋 *Bienvenido al bot satelital del ISAT*\n\n"
        "Usá los siguientes comandos:\n"
        "📷 /imagenes   → Solicitar imágenes SAR de una zona\n"
        "📉 /deformacion → Analizar deformación del terreno\n"
        "ℹ️ /ayuda       → Ver esta ayuda"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ── /imagenes ──
async def cmd_imagenes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["modo"] = "imagenes"
    await update.message.reply_text(
        "📷 *Solicitud de imágenes SAR*\n\n"
        "Enviá tu 📍 *ubicación* (o la de la zona de interés) para continuar.\n"
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
        "Enviá tu 📍 *ubicación* (o la de la zona de interés) para continuar.\n"
        "Usá /cancelar para salir.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ESPERANDO_UBICACION


# ── Recibir ubicación ──
async def recibir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = update.message.location
    lat = location.latitude
    lon = location.longitude

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        await update.message.reply_text("❌ Coordenadas inválidas. Intentá de nuevo.")
        return ESPERANDO_UBICACION

    modo = context.user_data.get("modo", "imagenes")

    await update.message.reply_text("⏳ Procesando solicitud, aguardá un momento...")

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