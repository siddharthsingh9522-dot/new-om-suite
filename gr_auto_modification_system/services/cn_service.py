"""
CN / GR / Docket / LR lookup service.

Wraps: GET /manual-cn/modification/{CN_NUMBER}
"""
import logging

from services.api_client import api_client
from utils.retry import PermanentAPIError, TemporaryAPIError

logger = logging.getLogger("gr_auto_mod.cn_service")


class CNNotFoundError(Exception):
    pass


class CNLookupError(Exception):
    """Wraps a temporary failure fetching CN details (safe to retry)."""


def fetch_cn_details(gr_number: str) -> dict:
    """
    Fetch the current CN/GR modification details from upstream.

    Returns the "data" object from the API response.
    Raises CNNotFoundError for a definitively-missing CN, or
    CNLookupError for a transient/upstream problem.
    """
    path = f"/manual-cn/modification/{gr_number}"
    try:
        response = api_client.get(path)
    except PermanentAPIError as exc:
        raise CNNotFoundError(f"GR/CN {gr_number} could not be found or is invalid: {exc}") from exc
    except TemporaryAPIError as exc:
        raise CNLookupError(f"Temporary failure fetching GR/CN {gr_number}: {exc}") from exc

    if not isinstance(response, dict) or response.get("status") != "success":
        message = (response or {}).get("message", "Unknown error") if isinstance(response, dict) else "Malformed response"
        raise CNNotFoundError(f"GR/CN {gr_number} lookup failed: {message}")

    data = response.get("data")
    if not data:
        raise CNNotFoundError(f"GR/CN {gr_number} returned no data.")

    return data
