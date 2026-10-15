import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://adal:adal@localhost:5432/adal")

GEN_MODEL = os.getenv("GEN_MODEL", "gemini-3.8-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

MAX_DISTANCE = float(os.getenv("MAX_DISTANCE", "0.45"))
TOP_K = int(os.getenv("TOP_K", "6"))

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
