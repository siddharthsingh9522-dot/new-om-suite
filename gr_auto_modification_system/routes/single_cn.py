"""
Single CN modification routes.
"""
import logging

from flask import Blueprint, render_template, request, jsonify

from config import settings
from models import db, Batch, BatchItem
from models.batch_item import STATUS_READY
from services.modification_service import build_record_preview, build_modification_payload, save_modification
from services.batch_service import create_single_cn_batch, log_audit
from services import auth_service
from utils.validators import is_valid_gr_number, validate_remark_length

logger = logging.getLogger("gr_auto_mod.routes.single_cn")
single_cn_bp = Blueprint("single_cn", __name__, url_prefix="/single-cn")


@single_cn_bp.before_request
def _require_modifier():
    # SECURITY FIX: utils/auth_decorators.py's login_required/
    # modifier_required_api existed but were never applied to any route
    # in this blueprint - every route here (including /confirm, which
    # performs a real save) was reachable by anyone with network access
    # to this app, logged in or not, modifier or not. A blueprint-wide
    # before_request is used instead of decorating each route
    # individually, so a future new route can't accidentally ship
    # unprotected by omission.
    from flask import jsonify, redirect, url_for
    is_api = request.path.startswith("/single-cn/preview") or request.path.startswith("/single-cn/confirm")
    if not auth_service.is_authenticated():
        if is_api:
            return jsonify({"ok": False, "error": "Please log in first.", "auth_required": True}), 401
        return redirect(url_for("auth.login_page"))
    if not auth_service.is_modifier():
        message = "This account does not have CN modification permission."
        if is_api:
            return jsonify({"ok": False, "error": message}), 403
        return redirect(url_for("dashboard.index", error="not_authorized"))


@single_cn_bp.route("/")
def index():
    return render_template("single_cn.html", save_api_ready=settings.save_api_ready())


@single_cn_bp.route("/preview", methods=["POST"])
def preview():
    payload = request.get_json(force=True, silent=True) or {}
    gr_number = str(payload.get("gr_number", "")).strip()
    new_remark = payload.get("new_remark", "")
    manual_party_code = payload.get("manual_party_code") or None

    if not is_valid_gr_number(gr_number):
        return jsonify({"ok": False, "error": "Please enter a valid numeric GR/CN/Docket/LR number."}), 400

    ok, err = validate_remark_length(new_remark)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    result = build_record_preview(gr_number, new_remark, manual_party_code)
    # Snapshots are large / not JSON-friendly for the client - drop from response
    result.pop("cn_snapshot", None)
    result.pop("party_snapshot", None)

    return jsonify({"ok": True, "preview": result})


@single_cn_bp.route("/confirm", methods=["POST"])
def confirm():
    payload = request.get_json(force=True, silent=True) or {}
    gr_number = str(payload.get("gr_number", "")).strip()
    new_remark = payload.get("new_remark", "")
    manual_party_code = payload.get("manual_party_code") or None
    edited_final_remark = payload.get("final_remark") or None
    dry_run = bool(payload.get("dry_run", True))

    if not is_valid_gr_number(gr_number):
        return jsonify({"ok": False, "error": "Invalid GR/CN number."}), 400

    # Re-fetch the LATEST data right before modifying, to reduce the risk
    # of overwriting changes made elsewhere since the preview was shown.
    fresh_preview = build_record_preview(gr_number, new_remark, manual_party_code)
    if fresh_preview["status"] not in (STATUS_READY, "ALREADY_APPLIED"):
        fresh_preview.pop("cn_snapshot", None)
        fresh_preview.pop("party_snapshot", None)
        return jsonify({"ok": False, "error": fresh_preview["message"], "preview": fresh_preview}), 409

    final_remark = edited_final_remark or fresh_preview["final_remark"]

    batch = create_single_cn_batch(gr_number, new_remark)
    item = batch.items.first()
    item.existing_party_code = fresh_preview.get("existing_party_code")
    item.new_party_code = fresh_preview.get("new_party_code")
    item.party_name = fresh_preview.get("party_name")
    item.billing_location = fresh_preview.get("billing_location")
    item.existing_remark = fresh_preview.get("existing_remark")
    item.new_remark = fresh_preview.get("new_remark")
    item.final_remark = final_remark
    item.status = fresh_preview["status"]
    if fresh_preview.get("cn_snapshot"):
        item.set_snapshot(fresh_preview["cn_snapshot"])
    db.session.commit()

    if fresh_preview["status"] == "ALREADY_APPLIED":
        item.status = "ALREADY_APPLIED"
        db.session.commit()
        return jsonify({
            "ok": True,
            "modified": False,
            "message": "This remark was already applied - no changes made.",
            "batch_id": batch.batch_id,
        })

    payload_for_save = build_modification_payload(
        fresh_preview["cn_snapshot"],
        fresh_preview["party_snapshot"],
        final_remark,
        current_user_id=(auth_service.current_user() or {}).get("user_id"),
    )

    item.attempts = 1
    save_result = save_modification(gr_number, payload_for_save)

    if save_result["success"]:
        item.status = "SUCCESS"
        item.validation_message = save_result["message"]
    elif not save_result["configured"]:
        item.status = STATUS_READY
        item.validation_message = save_result["message"]
    else:
        item.status = "FAILED"
        item.last_error = save_result["message"]
    db.session.commit()

    log_audit(batch.batch_id, gr_number, "SINGLE_CONFIRM", save_result["message"])

    return jsonify({
        "ok": True,
        "modified": save_result["success"],
        "configured": save_result["configured"],
        "message": save_result["message"],
        "batch_id": batch.batch_id,
        "final_remark": final_remark,
    })
