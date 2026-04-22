from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

from config import TOKEN, logger, ESPERANDO_UBICACION, ESPERANDO_FECHA_INICIO, ESPERANDO_FECHA_FIN, ESPERANDO_VELOCIDAD
from handlers import (
    fin,
    start,
    ayuda,
    mensaje_generico,
    cmd_imagenes,
    cmd_deformacion,
    cmd_velocidad,
    recibir_ubicacion,
    recibir_ubicacion_texto,
    recibir_fecha_inicio,
    recibir_fecha_fin,
    cancelar,
    mensaje_velocidad
)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("imagenes",    cmd_imagenes),
            CommandHandler("deformacion", cmd_deformacion),
            CommandHandler("velocidad", cmd_velocidad),
        ],
        states={
            ESPERANDO_UBICACION: [
                MessageHandler(filters.LOCATION, recibir_ubicacion),
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ubicacion_texto),
            ],
            ESPERANDO_FECHA_INICIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_fecha_inicio),
            ],
            ESPERANDO_FECHA_FIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_fecha_fin),
            ],
            ESPERANDO_VELOCIDAD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_velocidad)
            ]
        },
        fallbacks=[
            CommandHandler("cancelar", cancelar),
        ],
    )


    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",  ayuda))
    app.add_handler(CommandHandler("end", fin))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_generico))

    logger.info("Bot iniciado ✅")
    app.run_polling()


if __name__ == "__main__":
    main()