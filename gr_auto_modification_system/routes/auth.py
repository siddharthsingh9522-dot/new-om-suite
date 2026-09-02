"""
Login / logout routes against the existing upstream authentication system.
"""
import logging

from flask import Blueprint, render_template, request, redirect, url_for, jsonify

from services import auth_service
from services.auth_service import LoginError, LoginUnavailableError

logger = logging.getLogger("gr_auto_mod.routes.auth")
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET"])
def login_page():
    if auth_service.is_authenticated():
        return redirect(url_for("dashboard.index"))
    return render_template("login.html")


@auth_bp.route("/login", methods=["POST"])
def login_submit():
    payload = request.get_json(force=True, silent=True) or {}
    user_id = (payload.get("user_id") or "").strip()
    password = payload.get("password") or ""
    branch_code = (payload.get("branch_code") or "").strip()

    if not user_id or not password or not branch_code:
        return jsonify({"ok": False, "error": "User ID, password, and branch code are all required."}), 400

    try:
        session_data = auth_service.login(user_id, password, branch_code)
    except LoginError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    except LoginUnavailableError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    # Per spec: after login, check bulk permission for this branch too.
    bulk_allowed = auth_service.check_allow_bulk(branch_code)

    if not session_data["is_modifier"]:
        message = "Logged in, but this account does not have CN modification permission - preview only."
    else:
        message = "Logged in successfully."

    return jsonify({
        "ok": True,
        "message": message,
        "is_modifier": session_data["is_modifier"],
        "bulk_allowed": bulk_allowed,
        "display_name": session_data["display_name"],
    })


@auth_bp.route("/logout", methods=["POST"])
def logout():
    auth_service.logout()
    return jsonify({"ok": True})


@auth_bp.route("/status")
def status():
    user = auth_service.current_user()
    if not user:
        return jsonify({"ok": True, "authenticated": False})
    return jsonify({
        "ok": True,
        "authenticated": True,
        "display_name": user.get("display_name"),
        "branch_code": user.get("branch_code"),
        "is_modifier": user.get("is_modifier"),
        "bulk_allowed": user.get("bulk_allowed"),
    })
