"""
Party (customer) lookup / validation service.

Wraps: GET /manual-cn/details/{PARTY_CODE}
"""
import logging

from services.api_client import api_client
from utils.retry import PermanentAPIError, TemporaryAPIError

logger = logging.getLogger("gr_auto_mod.party_service")


class PartyNotFoundError(Exception):
    pass


class PartyLookupError(Exception):
    """Wraps a temporary failure fetching party details (safe to retry)."""


def fetch_party_details(party_code: str) -> dict:
    """
    Fetch and validate party details from upstream.

    Returns the "data" object from the API response.
    Raises PartyNotFoundError if the party code does not resolve to a
    real party, or PartyLookupError for a transient upstream problem.
    """
    path = f"/manual-cn/details/{party_code}"
    try:
        response = api_client.get(path)
    except PermanentAPIError as exc:
        raise PartyNotFoundError(f"Party code {party_code} is invalid: {exc}") from exc
    except TemporaryAPIError as exc:
        raise PartyLookupError(f"Temporary failure validating party {party_code}: {exc}") from exc

    if not isinstance(response, dict) or response.get("status") != "success":
        message = (response or {}).get("message", "Unknown error") if isinstance(response, dict) else "Malformed response"
        raise PartyNotFoundError(f"Party code {party_code} validation failed: {message}")

    data = response.get("data")
    if not data:
        raise PartyNotFoundError(f"Party code {party_code} returned no data.")

    return data
