"""
History / audit routes.
"""
from flask import Blueprint, render_template, request, jsonify, send_file

from models import Batch, AuditLog
from services.excel_service import generate_report

history_bp = Blueprint("history", __name__, url_prefix="/history")


@history_bp.route("/")
def index():
    search = request.args.get("q", "").strip()
    query = Batch.query.order_by(Batch.created_at.desc())
    if search:
        query = query.filter(
            (Batch.batch_id.ilike(f"%{search}%")) |
            (Batch.source_filename.ilike(f"%{search}%")) |
            (Batch.common_remark.ilike(f"%{search}%"))
        )
    batches = query.all()
    return render_template("history.html", batches=batches, search=search)


@history_bp.route("/<batch_id>")
def detail(batch_id):
    batch = Batch.query.filter_by(batch_id=batch_id).first_or_404()
    items = sorted(batch.items.all(), key=lambda i: i.serial_no)
    logs = AuditLog.query.filter_by(batch_id=batch_id).order_by(AuditLog.created_at.desc()).all()
    return render_template("history_detail.html", batch=batch, items=items, logs=logs)


@history_bp.route("/<batch_id>/export")
def export(batch_id):
    batch = Batch.query.filter_by(batch_id=batch_id).first_or_404()
    filepath = generate_report(batch, batch.items.all())
    return send_file(filepath, as_attachment=True, download_name=f"{batch.batch_id}_report.xlsx")


@history_bp.route("/<batch_id>/failed")
def failed_records(batch_id):
    batch = Batch.query.filter_by(batch_id=batch_id).first_or_404()
    failed = [i.to_dict() for i in batch.items.all() if i.status in ("FAILED", "ERROR", "INVALID_CN", "INVALID_PARTY")]
    return jsonify({"ok": True, "items": failed})
