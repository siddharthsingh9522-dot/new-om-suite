"""
BatchItem model: one GR/CN/Docket/LR record within a batch.
"""
import json
from datetime import datetime

from models.database import db

# ---------------------------------------------------------------------------
# Status values (kept as plain strings for SQLite portability)
# ---------------------------------------------------------------------------
STATUS_READY = "READY"
STATUS_PENDING = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_SUCCESS = "SUCCESS"                    # legacy / save succeeded, not yet verified
STATUS_VERIFIED_SUCCESS = "VERIFIED_SUCCESS"  # save succeeded AND re-fetch confirmed the change
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"  # save call succeeded but re-fetch didn't match
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"
STATUS_ALREADY_APPLIED = "ALREADY_APPLIED"
STATUS_INVALID_CN = "INVALID_CN"
STATUS_INVALID_PARTY = "INVALID_PARTY"
STATUS_ERROR = "ERROR"

# Statuses that should NOT be auto-retried by "Retry Failed"
TERMINAL_NO_RETRY = {
    STATUS_INVALID_CN,
    STATUS_INVALID_PARTY,
    STATUS_SKIPPED,
    STATUS_ALREADY_APPLIED,
    STATUS_SUCCESS,
    STATUS_VERIFIED_SUCCESS,
}

# Statuses considered "problematic" for the Error Center / ATTENTION REQUIRED
ATTENTION_STATUSES = {
    STATUS_INVALID_CN,
    STATUS_INVALID_PARTY,
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_VERIFICATION_FAILED,
}

# ---------------------------------------------------------------------------
# Change type values - what will actually change for this record
# ---------------------------------------------------------------------------
CHANGE_TYPE_PARTY_ONLY = "PARTY_ONLY"
CHANGE_TYPE_REMARK_ONLY = "REMARK_ONLY"
CHANGE_TYPE_PARTY_AND_REMARK = "PARTY_AND_REMARK"
CHANGE_TYPE_NO_CHANGE = "NO_CHANGE"

CHANGE_TYPE_LABELS = {
    CHANGE_TYPE_PARTY_ONLY: "PARTY ONLY",
    CHANGE_TYPE_REMARK_ONLY: "REMARK ONLY",
    CHANGE_TYPE_PARTY_AND_REMARK: "PARTY + REMARK",
    CHANGE_TYPE_NO_CHANGE: "NO CHANGE",
}


class BatchItem(db.Model):
    __tablename__ = "batch_items"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False)

    serial_no = db.Column(db.Integer, nullable=False, default=0)
    gr_number = db.Column(db.String(64), nullable=False, index=True)

    existing_party_code = db.Column(db.String(64), nullable=True)
    new_party_code = db.Column(db.String(64), nullable=True)
    party_name = db.Column(db.String(255), nullable=True)
    billing_location = db.Column(db.String(255), nullable=True)

    existing_remark = db.Column(db.Text, nullable=True)
    new_remark = db.Column(db.Text, nullable=True)

    # Auto-computed by the system every time a preview/refresh runs.
    auto_final_remark = db.Column(db.Text, nullable=True)
    # Set only if the operator manually edits the final remark for this row.
    user_final_remark = db.Column(db.Text, nullable=True)
    is_manually_edited = db.Column(db.Boolean, default=False)
    # The value actually used for save/preview = user_final_remark if
    # is_manually_edited else auto_final_remark. Kept as its own column so
    # existing code (payload builder, exports) has one authoritative field.
    final_remark = db.Column(db.Text, nullable=True)

    change_type = db.Column(db.String(30), default=CHANGE_TYPE_NO_CHANGE)
    party_changed = db.Column(db.Boolean, default=False)
    remark_changed = db.Column(db.Boolean, default=False)

    status = db.Column(db.String(30), default=STATUS_PENDING)
    validation_message = db.Column(db.Text, nullable=True)

    selected = db.Column(db.Boolean, default=False)

    attempts = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text, nullable=True)

    # --- Post-save verification (see services.modification_service.verify_after_save) ---
    verification_status = db.Column(db.String(30), nullable=True)  # None | VERIFIED_SUCCESS | VERIFICATION_FAILED
    actual_party_code_after_save = db.Column(db.String(64), nullable=True)
    actual_remark_after_save = db.Column(db.Text, nullable=True)

    # Short, safe (no secrets) summary of the last save API response, for audit.
    api_response_summary = db.Column(db.Text, nullable=True)

    # JSON snapshot of the original API record, for rollback/audit purposes
    original_snapshot_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def set_snapshot(self, data: dict):
        self.original_snapshot_json = json.dumps(data, default=str)

    def get_snapshot(self):
        if not self.original_snapshot_json:
            return None
        try:
            return json.loads(self.original_snapshot_json)
        except (json.JSONDecodeError, TypeError):
            return None

    def can_retry(self):
        return self.status not in TERMINAL_NO_RETRY

    def apply_manual_edit(self, new_value: str):
        """Operator manually changed the Final Remark for this row only."""
        self.user_final_remark = new_value
        self.is_manually_edited = True
        self.final_remark = new_value

    def reset_to_auto_generated(self):
        """Discard the manual edit and go back to the system-computed value."""
        self.user_final_remark = None
        self.is_manually_edited = False
        self.final_remark = self.auto_final_remark

    def to_dict(self):
        return {
            "id": self.id,
            "serial_no": self.serial_no,
            "gr_number": self.gr_number,
            "existing_party_code": self.existing_party_code,
            "new_party_code": self.new_party_code,
            "party_name": self.party_name,
            "billing_location": self.billing_location,
            "existing_remark": self.existing_remark,
            "new_remark": self.new_remark,
            "auto_final_remark": self.auto_final_remark,
            "user_final_remark": self.user_final_remark,
            "final_remark": self.final_remark,
            "is_manually_edited": self.is_manually_edited,
            "change_type": self.change_type,
            "change_type_label": CHANGE_TYPE_LABELS.get(self.change_type, self.change_type),
            "party_changed": self.party_changed,
            "remark_changed": self.remark_changed,
            "status": self.status,
            "validation_message": self.validation_message,
            "selected": self.selected,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "verification_status": self.verification_status,
            "actual_party_code_after_save": self.actual_party_code_after_save,
            "actual_remark_after_save": self.actual_remark_after_save,
        }
