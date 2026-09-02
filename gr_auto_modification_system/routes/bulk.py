"""
Bulk Excel modification routes.

Flow: UPLOAD -> CONFIGURE (remark/party) -> PREVIEW -> REVIEW/SELECT ->
CONFIRM -> EXECUTE (live progress) -> HISTORY/EXPORT
"""
import logging
import os
import threading

from flask import Blueprint, render_template, request, jsonify, send_file

from config import settings
from models import db, Batch, BatchItem
from services.excel_service import (
    list_sheet_names, load_sheet, analyze_gr_column, generate_report,
    generate_template, ExcelParseError,
)
from services.party_service import fetch_party_details, PartyNotFoundError, PartyLookupError
from services.batch_service import (
    create_bulk_batch, build_previews, summarize_counts, execute_batch,
    pause_batch, resume_batch, stop_batch, retry_failed, reset_control, log_audit,
)
from services import auth_service
from utils.helpers import allowed_excel_file, unique_upload_name, ensure_dirs, paginate
from utils.remark_parser import extract_party_code
from utils.validators import validate_remark_length

logger = logging.getLogger("gr_auto_mod.routes.bulk")
bulk_bp = Blueprint("bulk", __name__, url_prefix="/bulk")

ensure_dirs(settings.UPLOAD_FOLDER, settings.EXPORT_FOLDER)


@bulk_bp.before_request
def _require_modifier():
    # SECURITY FIX: see the identical note in routes/single_cn.py -
    # utils/auth_decorators.py's guards existed but were never applied to
    # any route here either, including /execute (a real bulk save).
    from flask import jsonify, redirect, url_for
    is_page_load = request.method == "GET" and request.path in ("/bulk/", "/bulk/template")
    if not auth_service.is_authenticated():
        if is_page_load:
            return redirect(url_for("auth.login_page"))
        return jsonify({"ok": False, "error": "Please log in first.", "auth_required": True}), 401
    if not auth_service.is_modifier():
        message = "This account does not have CN modification permission."
        if is_page_load:
            return redirect(url_for("dashboard.index", error="not_authorized"))
        return jsonify({"ok": False, "error": message}), 403


@bulk_bp.route("/")
def index():
    return render_template("bulk_excel.html", save_api_ready=settings.save_api_ready())


@bulk_bp.route("/template")
def download_template():
    filepath = generate_template()
    return send_file(filepath, as_attachment=True, download_name="gr_bulk_upload_template.xlsx")


@bulk_bp.route("/upload", methods=["POST"])
def upload():
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
        return jsonify({
            "ok": False,
            "error": f"File has {len(df)} rows, exceeding the maximum of {settings.MAX_EXCEL_ROWS}.",
        }), 400

    analysis = analyze_gr_column(df)
    analysis.pop("gr_values", None)  # not needed until confirmed

    return jsonify({
        "ok": True,
        "saved_filename": saved_name,
        "original_filename": file.filename,
        "sheets": sheets,
        "selected_sheet": sheets[0],
        "columns": list(df.columns),
        "analysis": analysis,
    })


@bulk_bp.route("/analyze-sheet", methods=["POST"])
def analyze_sheet():
    """Re-analyze after the user picks a different sheet or GR column."""
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


@bulk_bp.route("/detect-party", methods=["POST"])
def detect_party():
    payload = request.get_json(force=True, silent=True) or {}
    remark = payload.get("common_remark", "")

    ok, err = validate_remark_length(remark)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    party_code, method = extract_party_code(remark)
    if not party_code:
        return jsonify({"ok": True, "detected": False, "message": "Party Code could not be automatically detected."})

    try:
        party_data = fetch_party_details(party_code)
    except PartyNotFoundError as exc:
        return jsonify({"ok": True, "detected": True, "party_code": party_code, "valid": False, "message": str(exc)})
    except PartyLookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    return jsonify({
        "ok": True,
        "detected": True,
        "valid": True,
        "party_code": party_code,
        "method": method,
        "party_name": party_data.get("customerCustomerName"),
        "party_type": party_data.get("customerType"),
        "billing_location": party_data.get("branchBranchName"),
        "gst": party_data.get("customerGst"),
        "verified": party_data.get("verifiedFlg"),
    })


@bulk_bp.route("/create-batch", methods=["POST"])
def create_batch():
    payload = request.get_json(force=True, silent=True) or {}
    saved_filename = payload.get("saved_filename")
    original_filename = payload.get("original_filename")
    sheet_name = payload.get("sheet_name")
    gr_column = payload.get("gr_column")
    common_remark = payload.get("common_remark", "")

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

    # De-duplicate while preserving first-seen order; skip empty/invalid.
    from utils.validators import is_valid_gr_number
    seen = set()
    gr_numbers = []
    for v in analysis["gr_values"]:
        if v and is_valid_gr_number(v) and v not in seen:
            seen.add(v)
            gr_numbers.append(v)

    if not gr_numbers:
        return jsonify({"ok": False, "error": "No valid GR numbers found in the selected column."}), 400

    batch = create_bulk_batch(original_filename, sheet_name, analysis["column"], gr_numbers, common_remark)

    return jsonify({"ok": True, "batch_id": batch.batch_id, "total_gr": batch.total_gr})


def _run_preview_in_background(app, batch_id, manual_party_code):
    with app.app_context():
        batch = Batch.query.filter_by(batch_id=batch_id).first()
        if batch:
            build_previews(batch, manual_party_code=manual_party_code)


@bulk_bp.route("/<batch_id>/build-preview", methods=["POST"])
def build_preview_route(batch_id):
    from flask import current_app
    payload = request.get_json(force=True, silent=True) or {}
    manual_party_code = payload.get("manual_party_code") or None

    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    batch.status = "FETCHING"
    db.session.commit()

    app = current_app._get_current_object()
    thread = threading.Thread(target=_run_preview_in_background, args=(app, batch_id, manual_party_code), daemon=True)
    thread.start()

    return jsonify({"ok": True, "message": "Preview build started."})


@bulk_bp.route("/<batch_id>/preview-status")
def preview_status(batch_id):
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404
    counts = summarize_counts(batch)
    return jsonify({"ok": True, "status": batch.status, "counts": counts})


@bulk_bp.route("/<batch_id>/items")
def list_items(batch_id):
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    search_gr = request.args.get("gr", "").strip()
    search_party = request.args.get("party", "").strip()
    status_filter = request.args.get("status", "").strip()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 25))
    sort_by = request.args.get("sort_by", "serial_no")
    sort_dir = request.args.get("sort_dir", "asc")

    items = batch.items.all()

    if search_gr:
        items = [i for i in items if search_gr.lower() in (i.gr_number or "").lower()]
    if search_party:
        items = [i for i in items if search_party.lower() in (i.new_party_code or i.existing_party_code or "").lower()]
    if status_filter:
        items = [i for i in items if i.status == status_filter]

    reverse = sort_dir == "desc"
    try:
        items.sort(key=lambda i: (getattr(i, sort_by) is None, getattr(i, sort_by)), reverse=reverse)
    except (AttributeError, TypeError):
        pass

    page_result = paginate(items, page, per_page)
    return jsonify({
        "ok": True,
        "items": [i.to_dict() for i in page_result["items"]],
        "page": page_result["page"],
        "per_page": page_result["per_page"],
        "total": page_result["total"],
        "total_pages": page_result["total_pages"],
        "counts": summarize_counts(batch),
    })


@bulk_bp.route("/<batch_id>/item/<int:item_id>", methods=["PATCH"])
def update_item(batch_id, item_id):
    """Edit final remark, skip, or re-include a specific row."""
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    item = BatchItem.query.filter_by(id=item_id, batch_id=batch.id).first()
    if not item:
        return jsonify({"ok": False, "error": "Item not found."}), 404

    payload = request.get_json(force=True, silent=True) or {}
    if "final_remark" in payload:
        item.final_remark = payload["final_remark"]
    if "action" in payload:
        if payload["action"] == "skip":
            item.status = "SKIPPED"
        elif payload["action"] == "include_again":
            item.status = "READY"
        elif payload["action"] == "select":
            item.selected = True
        elif payload["action"] == "deselect":
            item.selected = False

    db.session.commit()
    return jsonify({"ok": True, "item": item.to_dict()})


@bulk_bp.route("/<batch_id>/item/<int:item_id>/refresh", methods=["POST"])
def refresh_item(batch_id, item_id):
    from services.modification_service import build_record_preview
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404
    item = BatchItem.query.filter_by(id=item_id, batch_id=batch.id).first()
    if not item:
        return jsonify({"ok": False, "error": "Item not found."}), 404

    preview = build_record_preview(item.gr_number, batch.common_remark, item.new_party_code)
    item.existing_party_code = preview.get("existing_party_code")
    item.new_party_code = preview.get("new_party_code") or item.new_party_code
    item.party_name = preview.get("party_name")
    item.billing_location = preview.get("billing_location")
    item.existing_remark = preview.get("existing_remark")
    item.auto_final_remark = preview.get("final_remark")
    if not item.is_manually_edited:
        item.final_remark = preview.get("final_remark")
    item.status = preview.get("status")
    item.validation_message = preview.get("message")
    item.selected = (item.status == "READY")
    if preview.get("cn_snapshot"):
        item.set_snapshot(preview["cn_snapshot"])
    db.session.commit()

    return jsonify({"ok": True, "item": item.to_dict()})


@bulk_bp.route("/<batch_id>/select-bulk", methods=["POST"])
def select_bulk(batch_id):
    """Select All / Select READY / Deselect Errors."""
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    payload = request.get_json(force=True, silent=True) or {}
    mode = payload.get("mode")

    items = batch.items.all()
    if mode == "select_all":
        for i in items:
            i.selected = True
    elif mode == "select_ready":
        for i in items:
            i.selected = i.status == "READY"
    elif mode == "deselect_errors":
        for i in items:
            if i.status in ("ERROR", "INVALID_CN", "INVALID_PARTY", "FAILED"):
                i.selected = False
    elif mode == "deselect_all":
        for i in items:
            i.selected = False

    db.session.commit()
    return jsonify({"ok": True, "counts": summarize_counts(batch)})


def _run_execution_in_background(app, batch_id, selected_ids, dry_run, current_user_id):
    with app.app_context():
        batch = Batch.query.filter_by(batch_id=batch_id).first()
        if batch:
            execute_batch(batch, selected_ids, dry_run=dry_run, current_user_id=current_user_id)


@bulk_bp.route("/<batch_id>/execute", methods=["POST"])
def execute(batch_id):
    from flask import current_app
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    payload = request.get_json(force=True, silent=True) or {}
    dry_run = bool(payload.get("dry_run", True))
    confirmation_text = payload.get("confirmation_text", "")
    selected_ids = payload.get("item_ids")

    if not selected_ids:
        selected_ids = [i.id for i in batch.items.filter_by(selected=True).all() if i.status == "READY"]

    expected = f"MODIFY {len(selected_ids)}"
    if not dry_run and confirmation_text.strip().upper() != expected:
        return jsonify({"ok": False, "error": f'Please type "{expected}" to confirm.'}), 400

    if not dry_run and not settings.save_api_ready():
        return jsonify({
            "ok": False,
            "error": "Save API is not configured yet. Only Dry Run / Preview mode is available.",
        }), 400

    batch.selected_gr = len(selected_ids)
    db.session.commit()
    reset_control(batch.batch_id)

    current_user_id = (auth_service.current_user() or {}).get("user_id")
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run_execution_in_background, args=(app, batch_id, selected_ids, dry_run, current_user_id), daemon=True
    )
    thread.start()

    log_audit(batch.batch_id, None, "EXECUTION_REQUESTED", f"dry_run={dry_run}, selected={len(selected_ids)}")
    return jsonify({"ok": True, "message": "Execution started."})


@bulk_bp.route("/<batch_id>/pause", methods=["POST"])
def pause(batch_id):
    pause_batch(batch_id)
    return jsonify({"ok": True})


@bulk_bp.route("/<batch_id>/resume", methods=["POST"])
def resume(batch_id):
    resume_batch(batch_id)
    return jsonify({"ok": True})


@bulk_bp.route("/<batch_id>/stop", methods=["POST"])
def stop(batch_id):
    stop_batch(batch_id)
    return jsonify({"ok": True})


@bulk_bp.route("/<batch_id>/retry-failed", methods=["POST"])
def retry_failed_route(batch_id):
    from flask import current_app
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404

    payload = request.get_json(force=True, silent=True) or {}
    dry_run = bool(payload.get("dry_run", True))
    current_user_id = (auth_service.current_user() or {}).get("user_id")

    app = current_app._get_current_object()

    def _bg():
        with app.app_context():
            b = Batch.query.filter_by(batch_id=batch_id).first()
            retry_failed(b, dry_run=dry_run, current_user_id=current_user_id)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"ok": True, "message": "Retrying failed records."})


@bulk_bp.route("/<batch_id>/export")
def export(batch_id):
    batch = Batch.query.filter_by(batch_id=batch_id).first()
    if not batch:
        return jsonify({"ok": False, "error": "Batch not found."}), 404
    filepath = generate_report(batch, batch.items.all())
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
