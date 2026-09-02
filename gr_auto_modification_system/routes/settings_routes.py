"""
Settings page: shows current (non-secret) runtime configuration and lets
an operator adjust the few values that are safe to change at runtime
(stored in AppSetting). Credentials are NEVER shown or editable here -
they only ever come from environment variables.
"""
from flask import Blueprint, render_template, request, jsonify

from config import settings
from models import AppSetting

settings_bp = Blueprint("settings_routes", __name__, url_prefix="/settings")

RUNTIME_KEYS = {
    "retry_count": ("API_RETRY_COUNT", int),
    "retry_backoff_seconds": ("API_RETRY_BACKOFF_BASE_SECONDS", float),
    "request_timeout_seconds": ("API_REQUEST_TIMEOUT_SECONDS", float),
    "bulk_concurrency": ("BULK_CONCURRENCY", int),
    "max_excel_rows": ("MAX_EXCEL_ROWS", int),
}


@settings_bp.route("/")
def index():
    current = {}
    for key, (attr, _cast) in RUNTIME_KEYS.items():
        stored = AppSetting.get(key)
        current[key] = stored if stored is not None else getattr(settings, attr)

    return render_template(
        "settings.html",
        current=current,
        api_base_url=settings.API_BASE_URL,
        save_api_ready=settings.save_api_ready(),
        save_api_url_configured=bool(settings.SAVE_API_URL),
        save_api_method=settings.SAVE_API_METHOD,
    )


@settings_bp.route("/update", methods=["POST"])
def update():
    payload = request.get_json(force=True, silent=True) or {}
    updated = {}
    for key, (attr, cast) in RUNTIME_KEYS.items():
        if key in payload:
            try:
                value = cast(payload[key])
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": f"Invalid value for {key}"}), 400
            AppSetting.set(key, value)
            updated[key] = value

    return jsonify({"ok": True, "updated": updated})
