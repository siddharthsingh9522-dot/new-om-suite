"""
Generic routes for the four NEW modules (Consignor, Consignee, Freight
Mode, Transport Mode). One set of view functions, parameterized by
`module_key` in the URL, shared across all four - see
config/modules_config.py for what makes each module different.

The ORIGINAL Billing Party routes (routes/single_cn.py, routes/bulk.py)
are completely separate files and are not touched or called by this one.
"""
import logging
import os
import threading

from flask import Blueprint, render_template, request, jsonify, send_file, current_app, abort

from config import settings
from config.modules_config import get_module, all_modules, MODULES
from models import db
from models.module_batch import ModuleBatch
from models.module_batch_item import ModuleBatchItem
from services.generic_modifier_service import build_record_preview_generic, build_modification_payload_generic, save_modification_generic
from services.generic_batch_service import (
    create_single_batch, create_bulk_batch, build_previews, summarize_counts,
    execute_batch, pause_batch, resume_batch, stop_batch, retry_failed,
    reset_control, log_audit,
)
from services.excel_service import (
    list_sheet_names, load_sheet, analyze_gr_column, ExcelParseError,
)
from services.ai_service import analyze_modification_request, ai_configured
from services import auth_service
from utils.auth_decorators import modifier_required_api, bulk_allowed_required_api
from utils.helpers import allowed_excel_file, unique_upload_name, ensure_dirs, paginate
from utils.validators import is_valid_gr_number, validate_remark_length

logger = logging.getLogger("gr_auto_mod.routes.modules")
modules_bp = Blueprint("modules", __name__, url_prefix="/modify/<module_key>")

ensure_dirs(settings.UPLOAD_FOLDER, settings.EXPORT_FOLDER)


@modules_bp.before_request
def _require_modifier():
    # SECURITY FIX: modifier_required_api/bulk_allowed_required_api were
    # only applied to 2 of the ~20 routes in this file (single_confirm,
    # bulk_execute) - everything else, including bulk_create_batch,
    # bulk_build_preview, and every page-load route, had no auth
    # enforcement at all. A blueprint-wide before_request replaces
    # relying on remembering to decorate each route individually - it
    # also means a real save can never be reached without both
    # is_modifier() and (for bulk paths) bulk_allowed(), regardless of
    # which specific route handles it.
    from flask import jsonify, redirect, url_for
    is_page_load = request.method == "GET" and (request.path.endswith("/single") or request.path.endswith("/bulk"))
    if not auth_service.is_authenticated():
        if is_page_load:
            return redirect(url_for("auth.login_page"))
        return jsonify({"ok": False, "error": "Please log in first.", "auth_required": True}), 401
    if not auth_service.is_modifier():
        message = "This account does not have CN modification permission."
        if is_page_load:
            return redirect(url_for("dashboard.index", error="not_authorized"))
        return jsonify({"ok": False, "error": message}), 403
    if "/bulk" in request.path and not auth_service.bulk_allowed():
        message = "Bulk modification is not enabled for your branch."
        if is_page_load:
            return redirect(url_for("dashboard.index", error="not_authorized"))
        return jsonify({"ok": False, "error": message}), 403


@modules_bp.url_value_preprocessor
def _validate_module(endpoint, values):
    module_key = values.get("module_key") if values else None
    if module_key not in MODULES:
        abort(404)


@modules_bp.route("/single")
def single_page(module_key):
    module = get_module(module_key)
    return render_template(
        "module_single.html", module=module,
        save_api_ready=settings.save_api_ready(),
        ai_configured=ai_configured(),
    )


@modules_bp.route("/single/preview", methods=["POST"])
def single_preview(module_key):
    payload = request.get_json(force=True, silent=True) or {}
    gr_number = str(payload.get("gr_number", "")).strip()
    new_value = payload.get("new_value")
    new_remark = payload.get("new_remark", "")

    if not is_valid_gr_number(gr_number):
        return jsonify({"ok": False, "error": "Please enter a valid numeric GR/CN/Docket/LR number."}), 400

    ok, err = validate_remark_length(new_remark)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    result = build_record_preview_generic(module_key, gr_number, new_value, new_remark)
    result.pop("cn_snapshot", None)
    result.pop("value_snapshot", None)

    ai_result = None
    if payload.get("include_ai_analysis") and ai_configured():
        ai_result = analyze_modification_request({
            "module": module_key,
            "gr_number": gr_number,
            "current_value": result.get("existing_value"),
            "new_value": result.get("new_value"),
            "existing_remark": result.get("existing_remark"),
            "new_remark": result.get("new_remark"),
            "proposed_final_remark": result.get("final_remark"),
            "change_type": result.get("change_type"),
        })

    return jsonify({"ok": True, "preview": result, "ai_analysis": ai_result})


@modules_bp.route("/single/confirm", methods=["POST"])
@modifier_required_api
def single_confirm(module_key):
    payload = request.get_json(force=True, silent=True) or {}
    gr_number = str(payload.get("gr_number", "")).strip()
    new_value = payload.get("new_value")
    new_remark = payload.get("new_remark", "")
    edited_final_remark = payload.get("final_remark") or None
    dry_run = bool(payload.get("dry_run", True))
    # Freight Mode PREPAID<->TO PAY billing-party suggestion (see
    # services/generic_modifier_service._freight_mode_billing_suggestion)
    # - opt-in only, confirmed via a real operator that the real system
    # does not apply this automatically.
    apply_billing_suggestion = bool(payload.get("apply_billing_suggestion", False))

    if not is_valid_gr_number(gr_number):
        return jsonify({"ok": False, "error": "Invalid GR/CN number."}), 400

    # Re-fetch the LATEST data right before modifying.
    fresh_preview = build_record_preview_generic(module_key, gr_number, new_value, new_remark)
    if fresh_preview["status"] not in ("READY", "ALREADY_APPLIED"):
        fresh_preview.pop("cn_snapshot", None)
        fresh_preview.pop("value_snapshot", None)
        return jsonify({"ok": False, "error": fresh_preview["message"], "preview": fresh_preview}), 409

    final_remark = edited_final_remark or fresh_preview["final_remark"]
    user = auth_service.current_user()
    created_by = user.get("user_id") if user else None

    billing_suggestion = fresh_preview.get("billing_party_suggestion")
    billing_override = billing_suggestion if (apply_billing_suggestion and billing_suggestion) else None

    batch = create_single_batch(module_key, gr_number, fresh_preview.get("new_value"), new_remark, created_by)
    item = batch.items.first()
    item.existing_value = fresh_preview.get("existing_value")
    item.new_value = fresh_preview.get("new_value")
    item.existing_value_label = fresh_preview.get("existing_value_label")
    item.new_value_label = fresh_preview.get("new_value_label")
    item.existing_remark = fresh_preview.get("existing_remark")
    item.new_remark = fresh_preview.get("new_remark")
    item.auto_final_remark = fresh_preview.get("final_remark")
    item.final_remark = final_remark
    item.change_type = fresh_preview.get("change_type")
    item.status = fresh_preview["status"]
    if fresh_preview.get("cn_snapshot"):
        item.set_snapshot(fresh_preview["cn_snapshot"])
    db.session.commit()

    if fresh_preview["status"] == "ALREADY_APPLIED":
        return jsonify({"ok": True, "modified": False, "message": "Nothing to change - already applied.", "batch_id": batch.batch_id})

    if dry_run:
        item.status = "READY"
        item.validation_message = "Dry run mode - no data was modified."
        db.session.commit()
        return jsonify({"ok": True, "modified": False, "message": "Dry run completed - no data modified.", "batch_id": batch.batch_id})

    payload_for_save = build_modification_payload_generic(
        module_key, fresh_preview["cn_snapshot"], fresh_preview.get("new_value"),
        fresh_preview.get("new_value_label"), final_remark,
        current_user_id=created_by,
        billing_party_override=billing_override,
    )
    item.attempts = 1
    save_result = save_modification_generic(module_key, gr_number, payload_for_save)

    if save_result["success"]:
        from services.generic_modifier_service import verify_after_save_generic
        verification = verify_after_save_generic(module_key, gr_number, fresh_preview.get("new_value"), final_remark)
        item.actual_value_after_save = verification.get("actual_value")
        item.actual_remark_after_save = verification.get("actual_remark")
        if verification["verified"]:
            item.status = "VERIFIED_SUCCESS"
            item.validation_message = "Save confirmed and verified against upstream."
        else:
            item.status = "VERIFICATION_FAILED"
            item.validation_message = verification.get("message")
    elif not save_result["configured"]:
        item.status = "READY"
        item.validation_message = save_result["message"]
    else:
        item.status = "FAILED"
        item.last_error = save_result["message"]
    db.session.commit()

    log_audit(batch.batch_id, gr_number, f"SINGLE_CONFIRM_{module_key.upper()}", save_result["message"])

    return jsonify({
        "ok": True,
        "modified": save_result["success"],
        "configured": save_result["configured"],
        "status": item.status,
        "message": save_result["message"],
        "batch_id": batch.batch_id,
        "final_remark": final_remark,
        "billing_party_suggestion_applied": bool(billing_override),
    })


# ---------------------------------------------------------------------------
# Bulk workflow
# ---------------------------------------------------------------------------

@modules_bp.route("/bulk")
def bulk_page(module_key):
    module = get_module(module_key)
    return render_template(
        "module_bulk.html", module=module,
        save_api_ready=settings.save_api_ready(),
        ai_configured=ai_configured(),
    )


@modules_bp.route("/bulk/upload", methods=["POST"])
def bulk_upload(module_key):
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"ok": False, "error": "No file selected."}), 400
    if not allowed_excel_file(file.filename, settings.ALLOWED_EXCEL_EXTENSIONS):
        return jsonify({"ok": False, "error": "Only .xlsx and .xls files are supported."}), 400

    saved_name = unique_upload_name(file.filename)
    filepath = os.path.join(settings.UPLOAD_FOLDER, saved_name)
    file.save(filepath)

    try:
        sheets = list_sheet_names(filepath)
        df = load_sheet(filepath, sheets[0])
    except ExcelParseError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if len(df) > settings.MAX_EXCEL_ROWS:
        return jsonify({"ok": False, "error": f"File has {len(df)} rows, exceeding the maximum of {settings.MAX_EXCEL_ROWS}."}), 400

    analysis = analyze_gr_column(df)
    analysis.pop("gr_values", None)

    return jsonify({
        "ok": True, "saved_filename": saved_name, "original_filename": file.filename,
        "sheets": sheets, "selected_sheet": sheets[0], "columns": list(df.columns), "analysis": analysis,
    })


@modules_bp.route("/bulk/analyze-sheet", methods=["POST"])
def bulk_analyze_sheet(module_key):
    payload = request.get_json(force=True, silent=True) or {}
    saved_filename = payload.get("saved_filename")
    sheet_name = payload.get("sheet_name")
    gr_column = payload.get("gr_column")

    filepath = os.path.join(settings.UPLOAD_FOLDER, saved_filename or "")
    if not saved_filename or not os.path.exists(filepath):
        return jsonify({"ok": False, "error": "Uploaded file not found. Please re-upload."}), 400

    try:
        df = load_sheet(filepath, sheet_name)
    except ExcelParseError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    analysis = analyze_gr_column(df, chosen_column=gr_column)
    analysis.pop("gr_values", None)
    return jsonify({"ok": True, "columns": list(df.columns), "analysis": analysis})


@modules_bp.route("/bulk/create-batch", methods=["POST"])
def bulk_create_batch(module_key):
    payload = request.get_json(force=True, silent=True) or {}
    saved_filename = payload.get("saved_filename")
    original_filename = payload.get("original_filename")
    sheet_name = payload.get("sheet_name")
    gr_column = payload.get("gr_column")
    new_value = payload.get("new_value")
    new_remark = payload.get("new_remark", "")

    filepath = os.path.join(settings.UPLOAD_FOLDER, saved_filename or "")
    if not saved_filename or not os.path.exists(filepath):
        return jsonify({"ok": False, "error": "Uploaded file not found. Please re-upload."}), 400

    try:
        df = load_sheet(filepath, sheet_name)
    except ExcelParseError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    analysis = analyze_gr_column(df, chosen_column=gr_column)
    if not analysis["column"]:
        return jsonify({"ok": False, "error": "Could not determine the GR column."}), 400

    seen = set()
    gr_numbers = []
    for v in analysis["gr_values"]:
        if v and is_valid_gr_number(v) and v not in seen:
            seen.add(v)
            gr_numbers.append(v)

    if not gr_numbers:
        return jsonify({"ok": False, "error": "No valid GR numbers found in the selected column."}), 400

    user = auth_service.current_user()
    created_by = user.get("user_id") if user else None

    batch = create_bulk_batch(module_key, original_filename, sheet_name, analysis["column"],
                               gr_numbers, new_value, new_remark, created_by)
    return jsonify({"ok": True, "batch_id": batch.batch_id, "total_gr": batch.total_gr})


def _run_preview_in_background(app, batch_id):
    batch = None
    with app.app_context():
        batch = ModuleBatch.query.filter_by(batch_id=batch_id).first()
    if batch:
        build_previews(app, batch)


@modules_bp.route("/bulk/<batch_id>/build-preview", methods=["POST"])
def bulk_build_preview(module_key, batch_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    batch.status = "FETCHING"
    db.session.commit()

    app = current_app._get_current_object()
    threading.Thread(target=_run_preview_in_background, args=(app, batch_id), daemon=True).start()
    return jsonify({"ok": True, "message": "Preview build started."})


@modules_bp.route("/bulk/<batch_id>/preview-status")
def bulk_preview_status(module_key, batch_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404
    return jsonify({"ok": True, "status": batch.status, "counts": summarize_counts(batch),
                    "config_error_message": batch.config_error_message})


@modules_bp.route("/bulk/<batch_id>/items")
def bulk_list_items(module_key, batch_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    search = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "").strip()
    only_changes = request.args.get("only_changes") == "1"
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 25))

    items = batch.items.all()

    if search:
        def _matches(i):
            haystacks = [i.gr_number, i.existing_value, i.new_value, i.existing_value_label,
                         i.new_value_label, i.existing_remark, i.final_remark]
            return any(search in str(h).lower() for h in haystacks if h)
        items = [i for i in items if _matches(i)]

    if status_filter == "MANUALLY_EDITED":
        items = [i for i in items if i.is_manually_edited]
    elif status_filter in ("VALUE_ONLY", "REMARK_ONLY", "VALUE_AND_REMARK"):
        items = [i for i in items if i.change_type == status_filter]
    elif status_filter:
        items = [i for i in items if i.status == status_filter]

    if only_changes:
        items = [i for i in items if i.status not in ("ALREADY_APPLIED", "SKIPPED")]

    items.sort(key=lambda i: i.serial_no)
    page_result = paginate(items, page, per_page)

    return jsonify({
        "ok": True, "items": [i.to_dict() for i in page_result["items"]],
        "page": page_result["page"], "per_page": page_result["per_page"],
        "total": page_result["total"], "total_pages": page_result["total_pages"],
        "counts": summarize_counts(batch),
    })


@modules_bp.route("/bulk/<batch_id>/item/<int:item_id>", methods=["PATCH"])
def bulk_update_item(module_key, batch_id, item_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404
    item = ModuleBatchItem.query.filter_by(id=item_id, batch_id=batch.id).first()
    if not item:
        return jsonify({"ok": False, "error": "Item not found."}), 404

    payload = request.get_json(force=True, silent=True) or {}
    if "final_remark" in payload:
        item.apply_manual_edit(payload["final_remark"])
    if payload.get("action") == "reset_to_auto":
        item.reset_to_auto_generated()
    elif payload.get("action") == "skip":
        item.status = "SKIPPED"
        item.selected = False
    elif payload.get("action") == "include_again":
        item.status = "READY"
    elif payload.get("action") == "select":
        item.selected = True
    elif payload.get("action") == "deselect":
        item.selected = False

    db.session.commit()
    return jsonify({"ok": True, "item": item.to_dict()})


@modules_bp.route("/bulk/<batch_id>/item/<int:item_id>/refresh", methods=["POST"])
def bulk_refresh_item(module_key, batch_id, item_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404
    item = ModuleBatchItem.query.filter_by(id=item_id, batch_id=batch.id).first()
    if not item:
        return jsonify({"ok": False, "error": "Item not found."}), 404

    preview = build_record_preview_generic(module_key, item.gr_number, batch.common_new_value, batch.common_remark)
    item.existing_value = preview.get("existing_value")
    item.new_value = preview.get("new_value")
    item.existing_value_label = preview.get("existing_value_label")
    item.new_value_label = preview.get("new_value_label")
    item.existing_remark = preview.get("existing_remark")
    item.auto_final_remark = preview.get("final_remark")
    if not item.is_manually_edited:
        item.final_remark = preview.get("final_remark")
    item.change_type = preview.get("change_type")
    item.status = preview.get("status")
    item.validation_message = preview.get("message")
    item.selected = (item.status == "READY")
    if preview.get("cn_snapshot"):
        item.set_snapshot(preview["cn_snapshot"])
    db.session.commit()
    return jsonify({"ok": True, "item": item.to_dict()})


@modules_bp.route("/bulk/<batch_id>/select-bulk", methods=["POST"])
def bulk_select_bulk(module_key, batch_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    mode = (request.get_json(force=True, silent=True) or {}).get("mode")
    items = batch.items.all()

    if mode == "select_all":
        for i in items: i.selected = True
    elif mode == "select_ready":
        for i in items: i.selected = (i.status == "READY")
    elif mode == "select_value_changes":
        for i in items: i.selected = (i.change_type in ("VALUE_ONLY", "VALUE_AND_REMARK") and i.status == "READY")
    elif mode == "select_remark_changes":
        for i in items: i.selected = (i.change_type in ("REMARK_ONLY", "VALUE_AND_REMARK") and i.status == "READY")
    elif mode == "select_manually_edited":
        for i in items: i.selected = i.is_manually_edited
    elif mode == "select_errors":
        for i in items: i.selected = (i.status in ("ERROR", "INVALID_CN", "INVALID_VALUE", "FAILED", "VERIFICATION_FAILED"))
    elif mode in ("deselect_all", "reset_selection"):
        for i in items:
            i.selected = (i.status == "READY") if mode == "reset_selection" else False

    db.session.commit()
    return jsonify({"ok": True, "counts": summarize_counts(batch)})


def _run_execution_in_background(app, batch_id, selected_ids, dry_run):
    batch = None
    with app.app_context():
        batch = ModuleBatch.query.filter_by(batch_id=batch_id).first()
    if batch:
        execute_batch(app, batch, selected_ids, dry_run=dry_run)


@modules_bp.route("/bulk/<batch_id>/execute", methods=["POST"])
@bulk_allowed_required_api
def bulk_execute(module_key, batch_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    payload = request.get_json(force=True, silent=True) or {}
    dry_run = bool(payload.get("dry_run", True))
    confirmation_text = payload.get("confirmation_text", "")
    selected_ids = payload.get("item_ids")

    if not selected_ids:
        selected_ids = [i.id for i in batch.items.filter_by(selected=True).all() if i.status == "READY"]

    if not selected_ids:
        batch.status = "NO_RECORDS_SELECTED"
        db.session.commit()
        return jsonify({"ok": False, "error": "No records are selected. Nothing to modify.", "status": batch.status}), 400

    expected = f"MODIFY {len(selected_ids)}"
    if not dry_run and confirmation_text.strip().upper() != expected:
        return jsonify({"ok": False, "error": f'Please type "{expected}" to confirm.'}), 400

    if not dry_run and not settings.save_api_ready():
        return jsonify({"ok": False, "error": "Save API is not configured yet. Only Dry Run / Preview mode is available."}), 400

    batch.selected_gr = len(selected_ids)
    db.session.commit()
    reset_control(batch.batch_id)

    app = current_app._get_current_object()
    threading.Thread(target=_run_execution_in_background, args=(app, batch_id, selected_ids, dry_run), daemon=True).start()
    log_audit(batch.batch_id, None, "EXECUTION_REQUESTED", f"dry_run={dry_run}, selected={len(selected_ids)}")
    return jsonify({"ok": True, "message": "Execution started."})


@modules_bp.route("/bulk/<batch_id>/pause", methods=["POST"])
def bulk_pause(module_key, batch_id):
    pause_batch(batch_id)
    return jsonify({"ok": True})


@modules_bp.route("/bulk/<batch_id>/resume", methods=["POST"])
def bulk_resume(module_key, batch_id):
    resume_batch(batch_id)
    return jsonify({"ok": True})


@modules_bp.route("/bulk/<batch_id>/stop", methods=["POST"])
def bulk_stop(module_key, batch_id):
    stop_batch(batch_id)
    return jsonify({"ok": True})


@modules_bp.route("/bulk/<batch_id>/retry-failed", methods=["POST"])
def bulk_retry_failed(module_key, batch_id):
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    dry_run = bool((request.get_json(force=True, silent=True) or {}).get("dry_run", True))
    app = current_app._get_current_object()

    def _bg():
        with app.app_context():
            b = ModuleBatch.query.filter_by(batch_id=batch_id).first()
            retry_failed(app, b, dry_run=dry_run)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"ok": True, "message": "Retrying failed records."})


@modules_bp.route("/bulk/<batch_id>/export")
def bulk_export(module_key, batch_id):
    from services.excel_service import generate_module_report
    batch = ModuleBatch.query.filter_by(batch_id=batch_id, module_key=module_key).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404
    module = get_module(module_key)
    filepath = generate_module_report(module, batch, batch.items.all())
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
