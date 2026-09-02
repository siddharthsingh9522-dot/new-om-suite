"""
ModuleBatchItem: the generic-engine equivalent of models.batch_item.BatchItem,
shared by the four NEW modules (Consignor, Consignee, Freight Mode,
Transport Mode). Separate table from `batch_items` (Billing Party's table).
"""
import json
from datetime import datetime

from models.database import db

STATUS_READY = "READY"
STATUS_PENDING = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_SUCCESS = "SUCCESS"
STATUS_VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"
STATUS_ALREADY_APPLIED = "ALREADY_APPLIED"
STATUS_INVALID_CN = "INVALID_CN"
STATUS_INVALID_VALUE = "INVALID_VALUE"  # generic form of INVALID_PARTY (code OR mode invalid)
STATUS_ERROR = "ERROR"

TERMINAL_NO_RETRY = {
    STATUS_INVALID_CN, STATUS_INVALID_VALUE, STATUS_SKIPPED,
    STATUS_ALREADY_APPLIED, STATUS_SUCCESS, STATUS_VERIFIED_SUCCESS,
}
ATTENTION_STATUSES = {
    STATUS_INVALID_CN, STATUS_INVALID_VALUE, STATUS_ERROR,
    STATUS_FAILED, STATUS_VERIFICATION_FAILED,
}

CHANGE_TYPE_VALUE_ONLY = "VALUE_ONLY"
CHANGE_TYPE_REMARK_ONLY = "REMARK_ONLY"
CHANGE_TYPE_VALUE_AND_REMARK = "VALUE_AND_REMARK"
CHANGE_TYPE_NO_CHANGE = "NO_CHANGE"

CHANGE_TYPE_LABELS = {
    CHANGE_TYPE_VALUE_ONLY: "VALUE ONLY",
    CHANGE_TYPE_REMARK_ONLY: "REMARK ONLY",
    CHANGE_TYPE_VALUE_AND_REMARK: "VALUE + REMARK",
    CHANGE_TYPE_NO_CHANGE: "NO CHANGE",
}


class ModuleBatchItem(db.Model):
    __tablename__ = "module_batch_items"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("module_batches.id"), nullable=False)

    serial_no = db.Column(db.Integer, nullable=False, default=0)
    gr_number = db.Column(db.String(64), nullable=False, index=True)

    # Generic "value" = party/customer code for code-kind modules, or the
    # mode code for dropdown-kind modules.
    existing_value = db.Column(db.String(120), nullable=True)
    new_value = db.Column(db.String(120), nullable=True)
    existing_value_label = db.Column(db.String(255), nullable=True)  # e.g. party/consignor name
    new_value_label = db.Column(db.String(255), nullable=True)

    existing_remark = db.Column(db.Text, nullable=True)
    new_remark = db.Column(db.Text, nullable=True)

    auto_final_remark = db.Column(db.Text, nullable=True)
    user_final_remark = db.Column(db.Text, nullable=True)
    is_manually_edited = db.Column(db.Boolean, default=False)
    final_remark = db.Column(db.Text, nullable=True)

    change_type = db.Column(db.String(30), default=CHANGE_TYPE_NO_CHANGE)
    value_changed = db.Column(db.Boolean, default=False)
    remark_changed = db.Column(db.Boolean, default=False)

    status = db.Column(db.String(30), default=STATUS_PENDING)
    validation_message = db.Column(db.Text, nullable=True)

    selected = db.Column(db.Boolean, default=False)

    attempts = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text, nullable=True)

    verification_status = db.Column(db.String(30), nullable=True)
    actual_value_after_save = db.Column(db.String(120), nullable=True)
    actual_remark_after_save = db.Column(db.Text, nullable=True)

    api_response_summary = db.Column(db.Text, nullable=True)
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
        self.user_final_remark = new_value
        self.is_manually_edited = True
        self.final_remark = new_value

    def reset_to_auto_generated(self):
        self.user_final_remark = None
        self.is_manually_edited = False
        self.final_remark = self.auto_final_remark

    def to_dict(self):
        return {
            "id": self.id,
            "serial_no": self.serial_no,
            "gr_number": self.gr_number,
            "existing_value": self.existing_value,
            "new_value": self.new_value,
            "existing_value_label": self.existing_value_label,
            "new_value_label": self.new_value_label,
            "existing_remark": self.existing_remark,
            "new_remark": self.new_remark,
            "auto_final_remark": self.auto_final_remark,
            "user_final_remark": self.user_final_remark,
            "final_remark": self.final_remark,
            "is_manually_edited": self.is_manually_edited,
            "change_type": self.change_type,
            "change_type_label": CHANGE_TYPE_LABELS.get(self.change_type, self.change_type),
            "value_changed": self.value_changed,
            "remark_changed": self.remark_changed,
            "status": self.status,
            "validation_message": self.validation_message,
            "selected": self.selected,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "verification_status": self.verification_status,
        }
