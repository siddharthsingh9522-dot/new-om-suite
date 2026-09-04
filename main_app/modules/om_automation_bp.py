"""
OM Automation V2 (web) — ported from OM_Automation_V2/web_app.py into a
Blueprint for the unified OM Suite app. Reuses the exact same business
logic (core/, api/, excel/, gst_search.py) as the original project.

Note: the GST-captcha flow drives a real headless Chrome browser via
Selenium (see api/gst_captcha.py -> gst_search.py). That needs Chrome +
a matching chromedriver on whatever machine runs this blueprint — see
the top-level README for the Render deployment note about this.
"""

import os
import uuid

from flask import (
    Blueprint, render_template, request,
    jsonify, send_from_directory, abort
)
from werkzeug.utils import secure_filename

from auth import login_required

from modules.om_automation.config import INPUT_DIR, OUTPUT_DIR, SECRET_KEY  # noqa: F401
from modules.om_automation.core.batch_runner import MANUAL_FETCHERS, BATCH_RUNNERS, run_master_manual
from modules.om_automation.web.jobs import job_manager
from modules.om_automation.api import gst_captcha

ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

om_bp = Blueprint(
    "om", __name__,
    url_prefix="/om",
    template_folder="../templates/om",
    static_folder="../static/om",
    static_url_path="/static",
)

PAGE_META = {
    "cn": {"title": "CN Query", "subtitle": "Check CN / Docket / LR / Billty status", "input_label": "CN No."},
    "gst": {"title": "GST Query", "subtitle": "Verify GSTIN details", "input_label": "GSTIN"},
    "party": {"title": "Party Code Query", "subtitle": "Lookup customer by party code", "input_label": "Party Code"},
    "master": {"title": "Master", "subtitle": "CN No. \u2192 Party Code \u2192 GSTIN \u2192 GST details, all in one", "input_label": "CN No."},
}


@om_bp.errorhandler(Exception)
def _om_json_error(e):
    """Safety net: any /om/api/... route that crashes with something other
    than the RuntimeError already handled locally used to fall through to
    Flask's default HTML error page — which broke every fetch() call on
    this screen with "Unexpected token '<' ... is not valid JSON", since
    the frontend always expects JSON back. Non-API page routes (rendering
    a template) still get Flask's normal error handling; this only
    intercepts the /om/api/ JSON endpoints.
    """
    from werkzeug.exceptions import HTTPException
    if request.path.startswith("/om/api/"):
        status = e.code if isinstance(e, HTTPException) else 500
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"}), status
    raise e


def _allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


@om_bp.route("/")
@login_required
def index():
    return render_template("om/index.html", pages=PAGE_META)


@om_bp.route("/api/manual/<page_key>", methods=["POST"])
@login_required
def manual_fetch(page_key):
    if page_key not in PAGE_META:
        return jsonify({"success": False, "message": "Unknown page"}), 404

    payload = request.get_json(silent=True) or {}
    value = str(payload.get("value", "")).strip()
    if value == "":
        return jsonify({"success": False, "message": "Value is required"}), 400

    if page_key == "master":
        result = run_master_manual(value)
        if not result["success"]:
            return jsonify({"success": False, "data": result["error"]})
        return jsonify({"success": True, "data": result["data"]})

    fetch_fn = MANUAL_FETCHERS[page_key]
    result = fetch_fn(value)
    if not result["success"]:
        return jsonify({
            "success": False,
            "data": {PAGE_META[page_key]["input_label"]: value, "Error": result["message"]}
        })
    return jsonify({"success": True, "data": result["data"]})


@om_bp.route("/api/gst/captcha/start_manual", methods=["POST"])
@login_required
def gst_captcha_start_manual():
    payload = request.get_json(silent=True) or {}
    gstin = str(payload.get("gstin", "")).strip().upper()
    if not gst_captcha.is_valid_gstin(gstin):
        return jsonify({"success": False, "message": "That doesn't look like a valid 15-character GSTIN."}), 400
    try:
        result = gst_captcha.start_session([gstin])
    except RuntimeError as e:
        return jsonify({"success": False, "message": str(e)}), 503
    return jsonify({"success": True, **result})


@om_bp.route("/api/gst/captcha/start_excel", methods=["POST"])
@login_required
def gst_captcha_start_excel():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"success": False, "message": "Only .xlsx / .xls files are allowed"}), 400

    try:
        result = gst_captcha.start_excel(file)
    except RuntimeError as e:
        return jsonify({"success": False, "message": str(e)}), 503
    if "error" in result:
        return jsonify({"success": False, "message": result["error"]}), 400
    return jsonify({"success": True, **result})


@om_bp.route("/api/gst/captcha/image")
@login_required
def gst_captcha_image():
    path = gst_captcha.captcha_image_path()
    if not path:
        abort(404)
    return send_from_directory(os.path.dirname(path), os.path.basename(path),
                                mimetype="image/png", max_age=0)


@om_bp.route("/api/gst/captcha/submit", methods=["POST"])
@login_required
def gst_captcha_submit():
    payload = request.get_json(silent=True) or {}
    result, status = gst_captcha.submit_captcha(payload.get("captcha", ""))
    return jsonify({"success": "error" not in result, **result}), status


@om_bp.route("/api/gst/captcha/stop", methods=["POST"])
@login_required
def gst_captcha_stop():
    result, status = gst_captcha.stop_session()
    return jsonify({"success": "error" not in result, **result}), status


@om_bp.route("/api/excel/<page_key>/start", methods=["POST"])
@login_required
def excel_start(page_key):
    if page_key not in BATCH_RUNNERS:
        return jsonify({"success": False, "message": "Unknown page"}), 404
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"success": False, "message": "Only .xlsx / .xls files are allowed"}), 400

    safe_name = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    save_path = os.path.join(INPUT_DIR, unique_name)
    file.save(save_path)

    runner = BATCH_RUNNERS[page_key]
    job_id = job_manager.start(runner, save_path)
    return jsonify({"success": True, "job_id": job_id})


@om_bp.route("/api/excel/status/<job_id>")
@login_required
def excel_status(job_id):
    job = job_manager.get(job_id)
    if job is None:
        return jsonify({"success": False, "message": "Unknown job"}), 404
    log_from = int(request.args.get("log_from", 0))
    snapshot = job.snapshot(log_from=log_from)
    return jsonify({"success": True, **snapshot})


@om_bp.route("/api/excel/stop/<job_id>", methods=["POST"])
@login_required
def excel_stop(job_id):
    job = job_manager.get(job_id)
    if job is None:
        return jsonify({"success": False, "message": "Unknown job"}), 404
    job_manager.stop(job_id)
    return jsonify({"success": True})


@om_bp.route("/download/<path:filename>")
@login_required
def download(filename):
    safe_name = secure_filename(filename)
    if safe_name != filename:
        abort(400)
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
