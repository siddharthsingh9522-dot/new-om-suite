"""
Dashboard route: high-level KPIs across all batches.
"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template

from config import settings
from models import Batch

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    all_batches = Batch.query.order_by(Batch.created_at.desc()).all()
    today_batches = [b for b in all_batches if b.created_at and b.created_at >= today_start]

    total_processed = sum((b.success_count or 0) + (b.failed_count or 0) for b in all_batches)
    total_success = sum(b.success_count or 0 for b in all_batches)
    total_failed = sum(b.failed_count or 0 for b in all_batches)
    success_rate = round((total_success / total_processed) * 100, 1) if total_processed else 0.0
    pending_records = sum(
        (b.total_gr or 0) - (b.success_count or 0) - (b.failed_count or 0) - (b.skipped_count or 0)
        for b in all_batches if b.status in ("DRAFT", "PREVIEWED", "CONFIRMED", "RUNNING", "PAUSED")
    )

    stats = {
        "today_batches": len(today_batches),
        "total_processed": total_processed,
        "success_rate": success_rate,
        "failed_records": total_failed,
        "pending_records": max(0, pending_records),
    }

    recent_batches = all_batches[:8]
    save_api_ready = settings.save_api_ready()

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_batches=recent_batches,
        save_api_ready=save_api_ready,
    )
