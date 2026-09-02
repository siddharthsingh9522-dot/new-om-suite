"""
Generic batch orchestration for the four NEW modules (Consignor, Consignee,
Freight Mode, Transport Mode) - the equivalent of services/batch_service.py
for models.module_batch.ModuleBatch / models.module_batch_item.ModuleBatchItem.

IMPORTANT - application context: every ThreadPoolExecutor worker below
explicitly pushes its own `app.app_context()`. Flask's app/request context
is thread-local and is NOT automatically inherited by worker threads spawned
from inside a context - only the thread that pushes app_context() can use
`db.session`/`Model.query` safely. Passing the real Flask app object into
each worker and wrapping its body in `with app.app_context():` is what
makes this safe under concurrency.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import settings
from config.modules_config import get_module
from models import db, AuditLog
from models.module_batch import (
    ModuleBatch, STATUS_DRAFT, STATUS_FETCHING, STATUS_CONFIGURATION_ERROR,
    STATUS_NO_RECORDS_SELECTED, STATUS_PREVIEW_READY, STATUS_DRY_RUN_RUNNING,
    STATUS_DRY_RUN_COMPLETED, STATUS_PROCESSING, STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS, STATUS_STOPPED, new_batch_id,
)
from models.module_batch_item import (
    ModuleBatchItem, STATUS_READY, STATUS_PENDING, STATUS_PROCESSING as ITEM_PROCESSING,
    STATUS_SUCCESS, STATUS_VERIFIED_SUCCESS, STATUS_VERIFICATION_FAILED,
    STATUS_FAILED, STATUS_SKIPPED, STATUS_ALREADY_APPLIED, STATUS_INVALID_CN,
    STATUS_INVALID_VALUE, STATUS_ERROR,
)
from services.generic_modifier_service import (
    build_record_preview_generic, build_modification_payload_generic,
    save_modification_generic, verify_after_save_generic,
)

logger = logging.getLogger("gr_auto_mod.generic_batch_service")

_control_lock = threading.Lock()
_batch_controls = {}


def _get_control(batch_id: str):
    with _control_lock:
        return _batch_controls.setdefault(batch_id, {"paused": False, "stopped": False})


def pause_batch(batch_id: str):
    _get_control(batch_id)["paused"] = True


def resume_batch(batch_id: str):
    _get_control(batch_id)["paused"] = False


def stop_batch(batch_id: str):
    _get_control(batch_id)["stopped"] = True


def reset_control(batch_id: str):
    with _control_lock:
        _batch_controls[batch_id] = {"paused": False, "stopped": False}


def log_audit(batch_id=None, gr_number=None, action="", details=""):
    entry = AuditLog(batch_id=batch_id, gr_number=gr_number, action=action, details=details)
    db.session.add(entry)
    db.session.commit()


def create_single_batch(module_key: str, gr_number: str, new_value, new_remark: str, created_by: str = None) -> ModuleBatch:
    batch = ModuleBatch(
        batch_id=new_batch_id(module_key),
        module_key=module_key,
        batch_type="single",
        common_remark=new_remark,
        common_new_value=new_value,
        total_gr=1,
        status=STATUS_DRAFT,
        created_by=created_by,
    )
    db.session.add(batch)
    db.session.flush()

    item = ModuleBatchItem(batch_id=batch.id, serial_no=1, gr_number=gr_number, status=STATUS_PENDING)
    db.session.add(item)
    db.session.commit()
    log_audit(batch.batch_id, gr_number, f"CREATE_SINGLE_{module_key.upper()}", f"Single batch created for {gr_number}")
    return batch


def create_bulk_batch(module_key: str, filename: str, sheet_name: str, gr_column: str,
                       gr_numbers: list, new_value, new_remark: str, created_by: str = None) -> ModuleBatch:
    batch = ModuleBatch(
        batch_id=new_batch_id(module_key),
        module_key=module_key,
        batch_type="bulk",
        source_filename=filename,
        sheet_name=sheet_name,
        gr_column=gr_column,
        common_remark=new_remark,
        common_new_value=new_value,
        total_gr=len(gr_numbers),
        status=STATUS_DRAFT,
        created_by=created_by,
    )
    db.session.add(batch)
    db.session.flush()

    for idx, gr in enumerate(gr_numbers, start=1):
        item = ModuleBatchItem(batch_id=batch.id, serial_no=idx, gr_number=gr, status=STATUS_PENDING)
        db.session.add(item)

    db.session.commit()
    log_audit(batch.batch_id, None, f"CREATE_BULK_{module_key.upper()}",
              f"Bulk batch created with {len(gr_numbers)} GR numbers from {filename}")
    return batch


def _apply_preview_to_item(item: ModuleBatchItem, preview: dict):
    item.existing_value = preview.get("existing_value")
    item.new_value = preview.get("new_value")
    item.existing_value_label = preview.get("existing_value_label")
    item.new_value_label = preview.get("new_value_label")
    item.existing_remark = preview.get("existing_remark")
    item.new_remark = preview.get("new_remark")
    item.auto_final_remark = preview.get("final_remark")
    if not item.is_manually_edited:
        item.final_remark = preview.get("final_remark")
    item.change_type = preview.get("change_type")
    item.value_changed = preview.get("value_changed", False)
    item.remark_changed = preview.get("remark_changed", False)
    item.status = preview.get("status")
    item.validation_message = preview.get("message")
    # Auto-select rule: READY records are selected by default; anything
    # else (ALREADY_APPLIED, INVALID_*, ERROR) is NOT auto-selected.
    item.selected = (item.status == STATUS_READY)
    if preview.get("cn_snapshot"):
        item.set_snapshot(preview["cn_snapshot"])


def build_previews(app, batch: ModuleBatch, concurrency: int = None):
    """
    Fetch + build previews for every item in the batch, using bounded
    concurrency. Each worker pushes its own app_context() - see module
    docstring for why this matters. This function pushes its own context
    for every section that touches the database, so it is safe to call
    regardless of whether the caller already has an active app context.
    """
    with app.app_context():
        module_key = batch.module_key
        concurrency = concurrency or settings.BULK_CONCURRENCY
        common_value = batch.common_new_value
        common_remark = batch.common_remark
        item_ids = [i.id for i in batch.items.all()]

    def _work(item_id):
        with app.app_context():
            item = ModuleBatchItem.query.get(item_id)
            try:
                preview = build_record_preview_generic(module_key, item.gr_number, common_value, common_remark)
                _apply_preview_to_item(item, preview)
            except Exception as exc:  # noqa: BLE001 - isolate per-record errors
                item.status = STATUS_ERROR
                item.validation_message = f"Unexpected error building preview: {exc}"
                logger.exception("Preview build failed for GR %s", item.gr_number)
            db.session.commit()

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(_work, iid) for iid in item_ids]
        for future in as_completed(futures):
            future.result()

    with app.app_context():
        batch = ModuleBatch.query.get(batch.id)
        counts = summarize_counts(batch)
        if counts["ready"] == 0 and counts["total"] > 0:
            # Nothing is actionable - either every record already matches,
            # or every record errored. Distinguish for a clearer status.
            if counts["error"] + counts["invalid"] == counts["total"]:
                batch.status = STATUS_CONFIGURATION_ERROR
                batch.config_error_message = "All records failed validation - nothing is ready to modify."
            else:
                batch.status = STATUS_PREVIEW_READY
        else:
            batch.status = STATUS_PREVIEW_READY
        db.session.commit()
        log_audit(batch.batch_id, None, "PREVIEW_BUILT", f"Preview built for {counts['total']} records")


def summarize_counts(batch: ModuleBatch):
    items = batch.items.all()
    return {
        "total": len(items),
        "ready": sum(1 for i in items if i.status == STATUS_READY),
        "already_applied": sum(1 for i in items if i.status == STATUS_ALREADY_APPLIED),
        "invalid": sum(1 for i in items if i.status in (STATUS_INVALID_CN, STATUS_INVALID_VALUE)),
        "error": sum(1 for i in items if i.status == STATUS_ERROR),
        "success": sum(1 for i in items if i.status in (STATUS_SUCCESS, STATUS_VERIFIED_SUCCESS)),
        "verification_failed": sum(1 for i in items if i.status == STATUS_VERIFICATION_FAILED),
        "failed": sum(1 for i in items if i.status == STATUS_FAILED),
        "skipped": sum(1 for i in items if i.status == STATUS_SKIPPED),
        "processing": sum(1 for i in items if i.status == ITEM_PROCESSING),
        "pending": sum(1 for i in items if i.status == STATUS_PENDING),
        "selected": sum(1 for i in items if i.selected),
        "manually_edited": sum(1 for i in items if i.is_manually_edited),
    }


def _execute_one(module_key: str, item: ModuleBatchItem, dry_run: bool):
    item.status = ITEM_PROCESSING
    db.session.commit()
    item.attempts += 1

    if dry_run:
        item.status = STATUS_READY
        item.validation_message = "Dry run mode - no data was modified."
        db.session.commit()
        return

    try:
        module = get_module(module_key)
        value_label = item.new_value_label
        payload = build_modification_payload_generic(
            module_key, item.get_snapshot() or {}, item.new_value, value_label, item.final_remark,
        )
        result = save_modification_generic(module_key, item.gr_number, payload)
    except Exception as exc:  # noqa: BLE001
        item.status = STATUS_FAILED
        item.last_error = str(exc)
        db.session.commit()
        return

    if not result.get("success"):
        if not result.get("configured"):
            item.status = STATUS_READY  # not configured - stays actionable, not a "failure"
        else:
            item.status = STATUS_FAILED
            item.last_error = result.get("message")
        item.validation_message = result.get("message")
        db.session.commit()
        return

    # Save call succeeded - do NOT trust it blindly. Re-fetch and verify.
    verification = verify_after_save_generic(module_key, item.gr_number, item.new_value, item.final_remark)
    item.actual_value_after_save = verification.get("actual_value")
    item.actual_remark_after_save = verification.get("actual_remark")
    if verification["verified"]:
        item.status = STATUS_VERIFIED_SUCCESS
        item.verification_status = STATUS_VERIFIED_SUCCESS
        item.validation_message = "Save confirmed and verified against upstream."
        item.last_error = None
    else:
        item.status = STATUS_VERIFICATION_FAILED
        item.verification_status = STATUS_VERIFICATION_FAILED
        item.validation_message = verification.get("message")
        item.last_error = verification.get("message")
    db.session.commit()


def execute_batch(app, batch: ModuleBatch, selected_item_ids: list, dry_run: bool = True, concurrency: int = None):
    module_key = batch.module_key
    concurrency = concurrency or settings.BULK_CONCURRENCY
    control = _get_control(batch.batch_id)
    control["paused"] = False
    control["stopped"] = False

    with app.app_context():
        batch = ModuleBatch.query.get(batch.id)
        batch.status = STATUS_DRY_RUN_RUNNING if dry_run else STATUS_PROCESSING
        batch.started_at = datetime.utcnow()
        batch.dry_run = dry_run
        db.session.commit()
        log_audit(batch.batch_id, None, "EXECUTION_STARTED", f"dry_run={dry_run}, selected={len(selected_item_ids)}")

    def _work(item_id):
        while control["paused"] and not control["stopped"]:
            time.sleep(0.5)
        if control["stopped"]:
            return
        with app.app_context():
            item = ModuleBatchItem.query.get(item_id)
            if item and (item.can_retry() or item.status == STATUS_READY):
                _execute_one(module_key, item, dry_run)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(_work, iid) for iid in selected_item_ids]
        for future in as_completed(futures):
            future.result()

    with app.app_context():
        batch = ModuleBatch.query.get(batch.id)
        counts = summarize_counts(batch)
        batch.success_count = counts["success"]
        batch.failed_count = counts["failed"] + counts["verification_failed"]
        batch.skipped_count = counts["skipped"]
        batch.already_applied_count = counts["already_applied"]
        batch.selected_gr = len(selected_item_ids)
        batch.finished_at = datetime.utcnow()

        if control["stopped"]:
            batch.status = STATUS_STOPPED
        elif dry_run:
            batch.status = STATUS_DRY_RUN_COMPLETED
        elif batch.failed_count > 0:
            batch.status = STATUS_COMPLETED_WITH_ERRORS
        else:
            batch.status = STATUS_COMPLETED
        db.session.commit()
        log_audit(batch.batch_id, None, "EXECUTION_FINISHED", f"status={batch.status}, counts={counts}")


def retry_failed(app, batch: ModuleBatch, dry_run: bool = True, concurrency: int = None):
    with app.app_context():
        failed_items = [i for i in batch.items.all() if i.status in (STATUS_FAILED, STATUS_VERIFICATION_FAILED)]
        failed_ids = [i.id for i in failed_items]
    execute_batch(app, batch, failed_ids, dry_run=dry_run, concurrency=concurrency)
