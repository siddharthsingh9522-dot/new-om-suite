"""
Route decorators enforcing the login / isModifier / allowbulk permission
matrix described in the upgrade spec:

    Modifier?   Bulk Allowed?   Single Modify   Bulk Modify
    No          N/A             blocked         blocked
    Yes         No              allowed         blocked
    Yes         Yes             allowed         allowed

Preview/read-only actions are NEVER blocked by these decorators - only the
actual "modify" actions require them, so an operator without permission can
still see what WOULD happen without being able to trigger it.
"""
import functools

from flask import jsonify, redirect, url_for

from services import auth_service


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not auth_service.is_authenticated():
            return redirect(url_for("auth.login_page"))
        return view(*args, **kwargs)
    return wrapped


def modifier_required_api(view):
    """For JSON API endpoints: returns a 403 JSON error instead of redirecting."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not auth_service.is_authenticated():
            return jsonify({"ok": False, "error": "Please log in first.", "auth_required": True}), 401
        if not auth_service.is_modifier():
            return jsonify({
                "ok": False,
                "error": "This account does not have CN modification permission.",
            }), 403
        return view(*args, **kwargs)
    return wrapped


def bulk_allowed_required_api(view):
    """For JSON API endpoints that perform BULK modification specifically."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not auth_service.is_authenticated():
            return jsonify({"ok": False, "error": "Please log in first.", "auth_required": True}), 401
        if not auth_service.is_modifier():
            return jsonify({
                "ok": False,
                "error": "This account does not have CN modification permission.",
            }), 403
        if not auth_service.bulk_allowed():
            return jsonify({
                "ok": False,
                "error": "This account/branch is not permitted to run bulk modifications.",
            }), 403
        return view(*args, **kwargs)
    return wrapped
