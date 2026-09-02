"""
Authentication / authorization against the existing upstream login system.

Wraps:
  POST /manual-cn/login                       -> establishes a session, returns isModifier
  GET  /manual-cn/allowbulk/{branchCode}       -> whether bulk operations are allowed

Session state (isModifier, branch, user id/name, bulk-allowed) is stored in
Flask's signed server-side session cookie (using the app's SECRET_KEY) -
never in a database table, and the password is never logged or stored
anywhere, ever - only sent once, directly to the upstream login call.
"""
import logging

from flask import session

from services.api_client import api_client
from utils.retry import PermanentAPIError, TemporaryAPIError

logger = logging.getLogger("gr_auto_mod.auth_service")

SESSION_KEY = "gr_auth"


class LoginError(Exception):
    """Raised for a definitive login rejection (bad credentials, etc)."""


class LoginUnavailableError(Exception):
    """Raised when the upstream login service could not be reached (transient)."""


def login(user_id: str, password: str, branch_code: str) -> dict:
    """
    Attempt to log in against the real upstream login endpoint.

    Returns a dict describing the authenticated session on success. Raises
    LoginError for a definitive rejection, LoginUnavailableError if the
    upstream could not be reached at all.
    """
    payload = {
        "userId": user_id,
        "password": password,
        "branchCode": branch_code,
        "isPdaUser": False,
    }
    try:
        response = api_client.send("POST", "/manual-cn/login", payload)
    except PermanentAPIError as exc:
        # Never echo the password back in any error message/log.
        logger.info("Login rejected for user_id=%s branch=%s", user_id, branch_code)
        raise LoginError("Login failed - please check your user ID, password, and branch code.") from exc
    except TemporaryAPIError as exc:
        raise LoginUnavailableError(f"Could not reach the login service: {exc}") from exc

    if not isinstance(response, dict):
        raise LoginUnavailableError("Login service returned an unexpected response.")

    # The upstream response shape beyond `isModifier` is not fully known;
    # extract common candidate fields defensively without assuming exact
    # key names, so this doesn't break if the real response differs
    # slightly from what's documented.
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    is_modifier = bool(data.get("isModifier", False))
    display_name = data.get("userName") or data.get("name") or user_id

    session_data = {
        "user_id": user_id,
        "branch_code": branch_code,
        "is_modifier": is_modifier,
        "display_name": display_name,
        "bulk_allowed": False,  # populated separately via check_allow_bulk()
    }
    session[SESSION_KEY] = session_data
    return session_data


def check_allow_bulk(branch_code: str) -> bool:
    """
    Check GET /manual-cn/allowbulk/{branchCode}. Fails CLOSED: any error
    (network, unexpected shape, etc.) results in bulk being disallowed
    rather than silently permitted.
    """
    try:
        response = api_client.get(f"/manual-cn/allowbulk/{branch_code}")
    except (PermanentAPIError, TemporaryAPIError) as exc:
        logger.warning("allowbulk check failed for branch=%s: %s", branch_code, exc)
        return False

    if not isinstance(response, dict):
        return False

    data = response.get("data") if isinstance(response.get("data"), dict) else response
    allowed = bool(data.get("allowed", False))

    current = session.get(SESSION_KEY)
    if current:
        current["bulk_allowed"] = allowed
        session[SESSION_KEY] = current

    return allowed


def logout():
    session.pop(SESSION_KEY, None)


def current_user():
    return session.get(SESSION_KEY)


def is_authenticated() -> bool:
    return session.get(SESSION_KEY) is not None


def is_modifier() -> bool:
    user = session.get(SESSION_KEY)
    return bool(user and user.get("is_modifier"))


def bulk_allowed() -> bool:
    user = session.get(SESSION_KEY)
    return bool(user and user.get("bulk_allowed"))
