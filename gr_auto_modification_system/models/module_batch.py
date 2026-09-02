"""
ModuleBatch: the generic-engine equivalent of models.batch.Batch, used by
the four NEW modules (Consignor, Consignee, Freight Mode, Transport Mode).

This is a SEPARATE table from `batches` - the original Billing Party
Batch/BatchItem tables are completely untouched by this file, so existing
Billing history/audit data can never be affected by the new modules.
"""
import uuid
from datetime import datetime

from models.database import db

# Same status vocabulary as models.batch, kept identical for consistency
# across the whole app (see models/batch.py for the full description of
# each status).
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


def _new_batch_id(module_key: str = "MOD"):
    prefix = (module_key or "MOD")[:3].upper()
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class ModuleBatch(db.Model):
    __tablename__ = "module_batches"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(64), unique=True, nullable=False)
    module_key = db.Column(db.String(40), nullable=False, index=True)

    batch_type = db.Column(db.String(20), nullable=False, default="bulk")  # 'single' | 'bulk'
    source_filename = db.Column(db.String(255), nullable=True)
    sheet_name = db.Column(db.String(120), nullable=True)
    gr_column = db.Column(db.String(120), nullable=True)

    common_remark = db.Column(db.Text, nullable=True)
    # For "code" modules: the party/customer code being applied to every row.
    # For "dropdown" modules: the mode value being applied to every row.
    common_new_value = db.Column(db.String(120), nullable=True)
    common_new_value_label = db.Column(db.String(255), nullable=True)

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

    created_by = db.Column(db.String(120), nullable=True)  # operator user id, from session

    items = db.relationship(
        "ModuleBatchItem", backref="batch", lazy="dynamic", cascade="all, delete-orphan"
    )

    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 2)
        return None

    def to_summary_dict(self):
        return {
            "batch_id": self.batch_id,
            "module_key": self.module_key,
            "batch_type": self.batch_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source_filename": self.source_filename,
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
            "common_new_value": self.common_new_value,
            "common_new_value_label": self.common_new_value_label,
            "config_error_message": self.config_error_message,
            "created_by": self.created_by,
        }


def new_batch_id(module_key: str) -> str:
    return _new_batch_id(module_key)
