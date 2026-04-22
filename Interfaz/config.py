import logging
import os
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# TOKEN
# ──────────────────────────────────────────────
TOKEN = os.getenv("TOKEN")

# ──────────────────────────────────────────────
# ESTADOS del ConversationHandler
# ──────────────────────────────────────────────
ESPERANDO_UBICACION    = 1
ESPERANDO_FECHA_INICIO = 2
ESPERANDO_FECHA_FIN    = 3
ESPERANDO_VELOCIDAD = 4

# ──────────────────────────────────────────────
# FORMATO DE FECHA ESPERADO
# ──────────────────────────────────────────────
FORMATO_FECHA = "%Y-%m-%d"
EJEMPLO_FECHA = "2024-01-15"

# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)