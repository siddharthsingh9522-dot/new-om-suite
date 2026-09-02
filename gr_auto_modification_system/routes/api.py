"""
Miscellaneous JSON API endpoints - system status used by the top bar.
"""
from flask import Blueprint, jsonify

from config import settings
from services.api_client import api_client
from utils.retry import PermanentAPIError, TemporaryAPIError

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/system-status")
def system_status():
    api_reachable = None
    try:
        # A harmless probe: fetch a known-shape endpoint with a dummy id.
        # We only care whether the upstream host answers at all, not
        # whether this particular CN exists.
        api_client.get("/manual-cn/modification/0")
        api_reachable = True
    except PermanentAPIError:
        # A clean 4xx means the host answered - service is reachable.
        api_reachable = True
    except TemporaryAPIError:
        api_reachable = False
    except Exception:  # noqa: BLE001
        api_reachable = False

    return jsonify({
        "ok": True,
        "api_reachable": api_reachable,
        "save_api_configured": settings.save_api_ready(),
        "api_base_url": settings.API_BASE_URL,
    })
