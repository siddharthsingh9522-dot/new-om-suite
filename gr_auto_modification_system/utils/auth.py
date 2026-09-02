"""
Session-based "current operator" context.

The application's own login (services/auth_service.py + routes/auth.py) is
layered on top of the existing upstream service-level auth already
configured via API_AUTH_MODE / API_BEARER_TOKEN / API_SESSION_COOKIE in
config/settings.py - that transport-level auth is untouched. This module
is only about WHO, within this application, is currently operating it.

Only non-secret identity fields returned by the login API are ever put
into the session: employee id/name/branch/isModifier/isKom. The password
is NEVER stored here, in the session, in a cookie, or logged anywhere.

The Flask session cookie is signed (itsdangerous, keyed off SECRET_KEY)
so the browser cannot forge or edit it, but it is not encrypted - do not
add anything sensitive to SESSION_KEYS below.
"""
from datetime import datetime, timezone

from flask import jsonify, redirect, request, session, url_for

SESSION_KEYS = ("userId", "userName", "branchCode", "branchName", "isModifier", "isKom", "loginAt")


def start_session(current_user: dict, is_kom_flag=None, lifetime_minutes: int = None):
    """Populate the Flask session from an authenticated login result."""
    session.clear()
    session["userId"] = current_user["userId"]
    session["userName"] = current_user["userName"]
    session["branchCode"] = current_user["branchCode"]
    session["branchName"] = current_user["branchName"]
    session["isModifier"] = bool(current_user["isModifier"])
    session["isKom"] = is_kom_flag
    session["loginAt"] = datetime.now(timezone.utc).isoformat()
    session.permanent = True


def end_session():
    session.clear()


def current_user():
    """Return the authenticated currentUser dict, or None if not logged in."""
    if not session.get("userId"):
        return None
    return {k: session.get(k) for k in SESSION_KEYS}


def is_authenticated() -> bool:
    return bool(session.get("userId"))


def is_modifier() -> bool:
    return bool(session.get("isModifier"))


def wants_json() -> bool:
    """
    Heuristic for whether the current request is an AJAX/JSON API call
    (should get a JSON 401/403 body) vs a normal browser page navigation
    (should be redirected to the login page).

    Every fetch() call this application's own JS makes goes through
    apiRequest() in static/js/app.js, which always sends
    "Content-Type: application/json" - real <a href>/<form>
    browser-initiated navigations never do.
    """
    content_type = (request.headers.get("Content-Type") or "").lower()
    if content_type.startswith("application/json"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def auth_required_response():
    """Standard response for "not logged in" - JSON 401 or redirect to login."""
    if wants_json():
        return jsonify({"ok": False, "error": "Please log in again.", "code": "AUTH_REQUIRED"}), 401
    return redirect(url_for("auth.login", next=request.path))


def modifier_required_response():
    """
    Standard response for "logged in, but not authorized to use Docket
    Modification" (isModifier is False). The backend remains the final
    authority here regardless of what the frontend shows/hides.
    """
    message = "Your account is not authorized to perform Docket Modifications."
    if wants_json():
        return jsonify({"ok": False, "error": message, "code": "NOT_MODIFIER"}), 403
    return redirect(url_for("dashboard.index", error="not_authorized"))


def guard_login():
    """Call at the top of a before_request hook. Returns a response to short-circuit, or None to continue."""
    if not is_authenticated():
        return auth_required_response()
    return None


def guard_modifier():
    """Call at the top of a before_request hook for modification-only blueprints."""
    resp = guard_login()
    if resp is not None:
        return resp
    if not is_modifier():
        return modifier_required_response()
    return None
