"""
Batch model: represents one bulk-excel modification run (or a single-CN run,
treated internally as a batch of size 1 for a unified history view).
"""
import uuid
from datetime import datetime

from models.database import db

# ---------------------------------------------------------------------------
# Batch status machine.
#
# DRAFT                 -> just created, items still PENDING
# FETCHING              -> preview build in progress
# CONFIGURATION_ERROR   -> Party Code could not be detected/validated; blocks preview
# NO_RECORDS_SELECTED   -> preview is ready but zero records are selected; blocks execution
# PREVIEW_READY         -> preview complete, at least one record is selectable
# DRY_RUN_RUNNING       -> a dry-run execution is in progress
# DRY_RUN_COMPLETED     -> a dry-run execution finished (NEVER "COMPLETED" - nothing was saved)
# PROCESSING            -> a REAL (non-dry-run) execution is in progress
# PAUSED                -> a real execution is paused mid-flight
# COMPLETED             -> real execution finished with zero failures
# COMPLETED_WITH_ERRORS -> real execution finished but some records failed/need attention
# STOPPED               -> execution was stopped safely before finishing all records
# ---------------------------------------------------------------------------
STATUS_DRAFT = "DRAFT"
STATUS_FETCHING = "FETCHING"
STATUS_CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
STATUS_NO_RECORDS_SELECTED = "NO_RECORDS_SELECTED"
STATUS_PREVIEW_READY = "PREVIEW_READY"
STATUS_DRY_RUN_RUNNING = "DRY_RUN_RUNNING"
STATUS_DRY_RUN_COMPLETED = "DRY_RUN_COMPLETED"
STATUS_PROCESSING = "PROCESSING"
STATUS_PAUSED = "PAUSED"
STATUS_COMPLETED = "COMPLETED"
STATUS_COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
STATUS_STOPPED = "STOPPED"

RUNNING_STATUSES = {STATUS_FETCHING, STATUS_DRY_RUN_RUNNING, STATUS_PROCESSING}
TERMINAL_EXECUTION_STATUSES = {
    STATUS_DRY_RUN_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS, STATUS_STOPPED,
}


def _new_batch_id():
    return "BATCH-" + uuid.uuid4().hex[:12].upper()


class Batch(db.Model):
    __tablename__ = "batches"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(64), unique=True, nullable=False, default=_new_batch_id)

    batch_type = db.Column(db.String(20), nullable=False, default="bulk")  # 'single' | 'bulk'
    source_filename = db.Column(db.String(255), nullable=True)
    sheet_name = db.Column(db.String(120), nullable=True)
    gr_column = db.Column(db.String(120), nullable=True)

    common_remark = db.Column(db.Text, nullable=True)
    detected_party_code = db.Column(db.String(64), nullable=True)
    party_name = db.Column(db.String(255), nullable=True)
    party_billing_location = db.Column(db.String(255), nullable=True)
    party_verified = db.Column(db.Boolean, default=False)

    total_gr = db.Column(db.Integer, default=0)
    selected_gr = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    skipped_count = db.Column(db.Integer, default=0)
    already_applied_count = db.Column(db.Integer, default=0)

    status = db.Column(db.String(30), default=STATUS_DRAFT)
    dry_run = db.Column(db.Boolean, default=True)
    config_error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    items = db.relationship(
        "BatchItem", backref="batch", lazy="dynamic", cascade="all, delete-orphan"
    )

    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 2)
        return None

    def to_summary_dict(self):
        return {
            "batch_id": self.batch_id,
            "batch_type": self.batch_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source_filename": self.source_filename,
            "sheet_name": self.sheet_name,
            "gr_column": self.gr_column,
            "total_gr": self.total_gr,
            "selected_gr": self.selected_gr,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "already_applied_count": self.already_applied_count,
            "status": self.status,
            "dry_run": self.dry_run,
            "duration_seconds": self.duration_seconds(),
            "common_remark": self.common_remark,
            "detected_party_code": self.detected_party_code,
            "party_name": self.party_name,
            "party_billing_location": self.party_billing_location,
            "party_verified": self.party_verified,
            "config_error_message": self.config_error_message,
        }
