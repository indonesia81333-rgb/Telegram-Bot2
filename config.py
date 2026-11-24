import os
from dotenv import load_dotenv

load_dotenv()


def _env(name, default=""):
    """Read an env var and strip the stray spaces/quotes/newlines hosts often leave in."""
    return os.getenv(name, default).strip().strip("\"'").strip()


def _int(name, default=0):
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# --- Telegram ---
API_ID = _int("API_ID")
API_HASH = _env("API_HASH", "")
BOT_TOKEN = _env("BOT_TOKEN", "")
OWNER_ID = _int("OWNER_ID")
# Optional: Telegram Premium user session string (enables files up to 4GB for the owner)
USER_SESSION = _env("USER_SESSION", "")

# --- Gofile ---
# Account API token: gofile.io > My Profile > Account API token
GOFILE_TOKEN = _env("GOFILE_TOKEN", "")
GOFILE_API = _env("GOFILE_API", "https://api.gofile.io").rstrip("/")
GOFILE_UPLOAD_URL = _env("GOFILE_UPLOAD_URL", "https://upload.gofile.io/uploadfile")
# Optional: put all user folders inside this folder id instead of the account root
GOFILE_ROOT_FOLDER_ID = _env("GOFILE_ROOT_FOLDER_ID", "")

# --- Link defaults ---
DEFAULT_EXPIRY_HOURS = _int("DEFAULT_EXPIRY_HOURS", 24)
MAX_EXPIRY_DAYS = _int("MAX_EXPIRY_DAYS", 30)
TIMEZONE = _env("TIMEZONE", "Asia/Kolkata")

# --- Limits ---
BOT_MAX_SIZE = 2 * 1024**3        # MTProto bot download limit
PREMIUM_MAX_SIZE = 4 * 1024**3    # Premium user session limit
DOWNLOAD_DIR = _env("DOWNLOAD_DIR", "downloads")

# --- Web / Render ---
PORT = _int("PORT", 8080)
APP_URL = _env("RENDER_EXTERNAL_URL", _env("APP_URL", ""))
DB_PATH = _env("DB_PATH", "data/bot.db")
