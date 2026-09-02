"""
Central application configuration.

Everything sensitive or environment-specific is read from environment
variables (see .env.example). Nothing here should ever contain a real
secret, cookie, or token.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class Settings:
    # --- Flask core ---
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-key-change-me")
    DEBUG = _bool(os.getenv("FLASK_DEBUG"), True)
    WTF_CSRF_ENABLED = _bool(os.getenv("WTF_CSRF_ENABLED"), True)

    # --- Database ---
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///gr_auto_mod.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Upstream read APIs ---
    API_BASE_URL = os.getenv("API_BASE_URL", "https://load.omone.in/utility-service/api")
    API_AUTH_MODE = os.getenv("API_AUTH_MODE", "none")  # none | bearer | cookie
    API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "")
    API_SESSION_COOKIE = os.getenv("API_SESSION_COOKIE", "")

    API_REQUEST_TIMEOUT_SECONDS = _float(os.getenv("API_REQUEST_TIMEOUT_SECONDS"), 15.0)
    API_RETRY_COUNT = _int(os.getenv("API_RETRY_COUNT"), 3)
    API_RETRY_BACKOFF_BASE_SECONDS = _float(os.getenv("API_RETRY_BACKOFF_BASE_SECONDS"), 1.5)
    API_RATE_LIMIT_PER_SECOND = _float(os.getenv("API_RATE_LIMIT_PER_SECOND"), 5.0)

    # --- Bulk processing ---
    BULK_CONCURRENCY = _int(os.getenv("BULK_CONCURRENCY"), 4)
    MAX_EXCEL_ROWS = _int(os.getenv("MAX_EXCEL_ROWS"), 5000)

    # --- SAVE / MODIFICATION API (placeholder until real endpoint known) ---
    SAVE_API_ENABLED = _bool(os.getenv("SAVE_API_ENABLED"), False)
    SAVE_API_URL = os.getenv("SAVE_API_URL", "")
    SAVE_API_METHOD = os.getenv("SAVE_API_METHOD", "POST")
    SAVE_API_AUTH_MODE = os.getenv("SAVE_API_AUTH_MODE", "none")

    # Fields from the original CN record that must NEVER be echoed back in a
    # save payload, even though build_modification_payload() otherwise
    # preserves the full record. manualCnNo/cnMamualCnDate are known to
    # trigger an upstream "already used in another CN" rejection when
    # resent verbatim - see services/modification_service.py for details.
    # Add to this list (via SAVE_PAYLOAD_EXTRA_EXCLUDED_FIELDS env var,
    # comma-separated) if other fields turn out to cause similar problems.
    SAVE_PAYLOAD_EXCLUDED_FIELDS = {"manualCnNo", "cnMamualCnDate"} | {
        f.strip() for f in os.getenv("SAVE_PAYLOAD_EXTRA_EXCLUDED_FIELDS", "").split(",") if f.strip()
    }

    # --- Storage ---
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, os.getenv("UPLOAD_FOLDER", "uploads"))
    EXPORT_FOLDER = os.path.join(BASE_DIR, os.getenv("EXPORT_FOLDER", "exports"))

    ALLOWED_EXCEL_EXTENSIONS = {"xlsx", "xls"}

    # --- Gemini AI copilot (advisory only - see services/ai_service.py) ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    # NOTE: verify this against whatever model your API key actually has
    # access to and override via GEMINI_MODEL if needed - model names/
    # availability change over time and shouldn't be hardcoded blindly.
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    GEMINI_TIMEOUT_SECONDS = _float(os.getenv("GEMINI_TIMEOUT_SECONDS"), 10.0)

    @classmethod
    def save_api_ready(cls):
        """Whether the real save/modification endpoint has been configured."""
        return bool(cls.SAVE_API_ENABLED and cls.SAVE_API_URL)


settings = Settings()
