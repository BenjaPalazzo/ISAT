import json
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import (
    logger,
    ESPERANDO_UBICACION,
    ESPERANDO_FECHA_INICIO,
    ESPERANDO_FECHA_FIN,
    EJEMPLO_FECHA,
)
from utils import extraer_ubicacion_de_texto, parsear_fecha, validar_rango_fechas
from api import consultar_imagenes, consultar_deformacion


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

async def _procesar_consulta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Llama a la API con los datos guardados en user_data y responde."""
    lat          = context.user_data["lat"]
    lon          = context.user_data["lon"]
    fecha_inicio = context.user_data["fecha_inicio"]
    fecha_fin    = context.user_data["fecha_fin"]
    modo         = context.user_data.get("modo", "imagenes")

    await update.message.reply_text(
        f"⏳ Procesando solicitud, aguardá un momento...",
    )

    if modo == "imagenes":
        resultado = await consultar_imagenes(lat, lon, fecha_inicio, fecha_fin)
        titulo = "📷 *Resultado — Imágenes SAR*"
    else:
        resultado = await consultar_deformacion(lat, lon, fecha_inicio, fecha_fin)
        titulo = "📉 *Resultado — Deformación del terreno*"

    respuesta = (
        f"{titulo}\n\n"
        f"```json\n{json.dumps(resultado, indent=2, ensure_ascii=False)}\n```"
    )
    await update.message.reply_text(respuesta, parse_mode="Markdown")

    # ── Mensaje de cierre ──
    await update.message.reply_text(
        "✅ Consulta finalizada.\n\n"
        "¿Necesitás algo más? Usá /imagenes o /deformacion para hacer otra consulta."
    )


# ──────────────────────────────────────────────
# COMANDOS GENERALES
# ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "👋 *Bienvenido al bot satelital del ISAT*\n\n"
        "Usá los siguientes comandos:\n"
        "📷 /imagenes    → Solicitar imágenes SAR de una zona\n"
        "📉 /deformacion → Analizar deformación del terreno\n"
        "ℹ️ /ayuda        → Ver esta ayuda \n"
        "🔚 /end     → Finalizar proceso"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def mensaje_generico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 *Bot satelital ISAT*\n\n"
        "Usá /imagenes o /deformacion para comenzar.",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
# PASO 1 — Elegir modo
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# PASO 2 — Recibir ubicación
# ──────────────────────────────────────────────

async def recibir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para pin nativo de Telegram."""
    location = update.message.location
    lat = location.latitude
    lon = location.longitude

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        await update.message.reply_text("❌ Coordenadas inválidas. Intentá de nuevo.")
        return ESPERANDO_UBICACION

    context.user_data["lat"] = lat
    context.user_data["lon"] = lon

    await update.message.reply_text(
        f"📍 Ubicación recibida: `{lat}, {lon}`\n\n"
        f"Ahora ingresá la *fecha de inicio* en formato `YYYY-MM-DD`\n"
        f"Ejemplo: `{EJEMPLO_FECHA}`",
        parse_mode="Markdown",
    )
    return ESPERANDO_FECHA_INICIO


async def recibir_ubicacion_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para links de Maps, OpenStreetMap o coordenadas escritas."""
    resultado = extraer_ubicacion_de_texto(update.message.text)

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

    context.user_data["lat"] = lat
    context.user_data["lon"] = lon

    await update.message.reply_text(
        f"📍 Ubicación recibida: `{lat}, {lon}`\n\n"
        f"Ahora ingresá la *fecha de inicio* en formato `YYYY-MM-DD`\n"
        f"Ejemplo: `{EJEMPLO_FECHA}`",
        parse_mode="Markdown",
    )
    return ESPERANDO_FECHA_INICIO


# ──────────────────────────────────────────────
# PASO 3 — Recibir fecha de inicio
# ──────────────────────────────────────────────

async def recibir_fecha_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha = parsear_fecha(update.message.text)

    if fecha is None:
        await update.message.reply_text(
            f"❌ Formato inválido. Usá `YYYY-MM-DD`, por ejemplo: `{EJEMPLO_FECHA}`",
            parse_mode="Markdown",
        )
        return ESPERANDO_FECHA_INICIO

    context.user_data["fecha_inicio"] = fecha.strftime("%Y-%m-%d")
    context.user_data["fecha_inicio_dt"] = fecha

    await update.message.reply_text(
        f"✅ Fecha de inicio: `{context.user_data['fecha_inicio']}`\n\n"
        f"Ahora ingresá la *fecha de fin* en formato `YYYY-MM-DD`\n"
        f"Ejemplo: `{EJEMPLO_FECHA}`",
        parse_mode="Markdown",
    )
    return ESPERANDO_FECHA_FIN


# ──────────────────────────────────────────────
# PASO 4 — Recibir fecha de fin y procesar
# ──────────────────────────────────────────────

async def recibir_fecha_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha = parsear_fecha(update.message.text)

    if fecha is None:
        await update.message.reply_text(
            f"❌ Formato inválido. Usá `YYYY-MM-DD`, por ejemplo: `{EJEMPLO_FECHA}`",
            parse_mode="Markdown",
        )
        return ESPERANDO_FECHA_FIN

    # Validar rango
    error = validar_rango_fechas(context.user_data["fecha_inicio_dt"], fecha)
    if error:
        await update.message.reply_text(error)
        return ESPERANDO_FECHA_FIN

    context.user_data["fecha_fin"] = fecha.strftime("%Y-%m-%d")

    await _procesar_consulta(update, context)
    return ConversationHandler.END


async def fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 ¡Hasta luego! Si necesitás consultar algo más, escribí /start."
    )

# ──────────────────────────────────────────────
# CANCELAR
# ──────────────────────────────────────────────

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operación cancelada. Usá /imagenes o /deformacion para empezar de nuevo."
    )
    return ConversationHandler.END