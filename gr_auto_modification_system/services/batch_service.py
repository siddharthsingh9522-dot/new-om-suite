"""
Batch orchestration service.

Handles:
 - Creating a Batch + BatchItem rows from an Excel upload or a single CN
 - Building previews concurrently (bounded thread pool) with retry/backoff
 - Executing (actually invoking save_modification) with pause/resume/stop
 - Retrying failed items
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import settings
from models import db, Batch, BatchItem, AuditLog
from models.batch_item import (
    STATUS_READY, STATUS_PENDING, STATUS_PROCESSING, STATUS_SUCCESS,
    STATUS_FAILED, STATUS_SKIPPED, STATUS_ALREADY_APPLIED,
    STATUS_INVALID_CN, STATUS_INVALID_PARTY, STATUS_ERROR,
)
from services.modification_service import (
    build_record_preview, build_modification_payload, save_modification,
)

logger = logging.getLogger("gr_auto_mod.batch_service")

# In-memory control flags per batch_id for pause/resume/stop.
# (Kept in-process; fine for a single-worker deployment. For multi-worker
# deployments this should move to a shared store like Redis.)
_control_lock = threading.Lock()
_batch_controls = {}  # batch_id (str) -> {"paused": bool, "stopped": bool}


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


def create_single_cn_batch(gr_number: str, new_remark: str) -> Batch:
    batch = Batch(
        batch_type="single",
        common_remark=new_remark,
        total_gr=1,
        status="DRAFT",
    )
    db.session.add(batch)
    db.session.flush()

    item = BatchItem(batch_id=batch.id, serial_no=1, gr_number=gr_number, status=STATUS_PENDING)
    db.session.add(item)
    db.session.commit()
    log_audit(batch.batch_id, gr_number, "CREATE_SINGLE", f"Single CN batch created for {gr_number}")
    return batch


def create_bulk_batch(filename: str, sheet_name: str, gr_column: str, gr_numbers: list, common_remark: str) -> Batch:
    batch = Batch(
        batch_type="bulk",
        source_filename=filename,
        sheet_name=sheet_name,
        gr_column=gr_column,
        common_remark=common_remark,
        total_gr=len(gr_numbers),
        status="DRAFT",
    )
    db.session.add(batch)
    db.session.flush()

    for idx, gr in enumerate(gr_numbers, start=1):
        item = BatchItem(batch_id=batch.id, serial_no=idx, gr_number=gr, status=STATUS_PENDING)
        db.session.add(item)

    db.session.commit()
    log_audit(batch.batch_id, None, "CREATE_BULK", f"Bulk batch created with {len(gr_numbers)} GR numbers from {filename}")
    return batch


def _apply_preview_to_item(item: BatchItem, preview: dict):
    item.existing_party_code = preview.get("existing_party_code")
    item.new_party_code = preview.get("new_party_code")
    item.party_name = preview.get("party_name")
    item.billing_location = preview.get("billing_location")
    item.existing_remark = preview.get("existing_remark")
    item.new_remark = preview.get("new_remark")
    item.auto_final_remark = preview.get("final_remark")
    if not item.is_manually_edited:
        item.final_remark = preview.get("final_remark")
    item.status = preview.get("status")
    item.validation_message = preview.get("message")
    # Auto-select rule: READY records are selected by default; anything
    # else (ALREADY_APPLIED, INVALID_*, ERROR) is NOT auto-selected. This
    # matters because the underlying `selected` column defaults to False -
    # without this line every item would silently stay unselected forever.
    item.selected = (item.status == STATUS_READY)
    if preview.get("cn_snapshot"):
        item.set_snapshot(preview["cn_snapshot"])


def build_previews(batch: Batch, manual_party_code: str = None, concurrency: int = None):
    """
    Fetch + build previews for every item in the batch, using bounded
    concurrency. Runs synchronously (caller may run this in a background
    thread if desired) and commits progressively so a UI can poll status.

    BUG FIX: each ThreadPoolExecutor worker below runs in its OWN thread,
    which does NOT inherit the Flask application context that the caller
    pushed in its own thread - Flask's app/request context is thread-local.
    Every worker was previously crashing immediately with "RuntimeError:
    Working outside of application context" as soon as it touched the DB,
    which left the batch stuck at status="FETCHING" forever. Each worker
    now explicitly pushes app.app_context() for itself (matching the
    pattern already used in services/generic_batch_service.py).
    """
    from flask import current_app
    app = current_app._get_current_object()
    concurrency = concurrency or settings.BULK_CONCURRENCY
    items = batch.items.all()
    item_ids = [i.id for i in items]

    def _work(item_id):
        with app.app_context():
            item = BatchItem.query.get(item_id)
            if not item:
                return None
            try:
                preview = build_record_preview(item.gr_number, batch.common_remark, manual_party_code)
                _apply_preview_to_item(item, preview)
            except Exception as exc:  # noqa: BLE001 - isolate per-record errors
                item.status = STATUS_ERROR
                item.validation_message = f"Unexpected error building preview: {exc}"
                logger.exception("Preview build failed for GR %s", item.gr_number)
            db.session.commit()
            return item.gr_number

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(_work, iid) for iid in item_ids]
        for future in as_completed(futures):
            future.result()

    batch.status = "PREVIEWED"
    db.session.commit()
    log_audit(batch.batch_id, None, "PREVIEW_BUILT", f"Preview built for {len(items)} records")


def summarize_counts(batch: Batch):
    items = batch.items.all()
    counts = {
        "total": len(items),
        "ready": sum(1 for i in items if i.status == STATUS_READY),
        "already_applied": sum(1 for i in items if i.status == STATUS_ALREADY_APPLIED),
        "invalid": sum(1 for i in items if i.status in (STATUS_INVALID_CN, STATUS_INVALID_PARTY)),
        "error": sum(1 for i in items if i.status == STATUS_ERROR),
        "success": sum(1 for i in items if i.status == STATUS_SUCCESS),
        "failed": sum(1 for i in items if i.status == STATUS_FAILED),
        "skipped": sum(1 for i in items if i.status == STATUS_SKIPPED),
        "processing": sum(1 for i in items if i.status == STATUS_PROCESSING),
        "pending": sum(1 for i in items if i.status == STATUS_PENDING),
    }
    return counts


def _execute_one(item: BatchItem, dry_run: bool, current_user_id: str = None):
    item.status = STATUS_PROCESSING
    db.session.commit()

    item.attempts += 1

    if dry_run:
        item.status = STATUS_READY
        item.validation_message = "Dry run mode - no data was modified."
        db.session.commit()
        return

    try:
        payload = build_modification_payload(
            item.get_snapshot() or {},
            {"customerCustomerCode": item.new_party_code, "customerCustomerName": item.party_name},
            item.final_remark,
            current_user_id=current_user_id,
        )
        result = save_modification(item.gr_number, payload)
    except Exception as exc:  # noqa: BLE001
        item.status = STATUS_FAILED
        item.last_error = str(exc)
        db.session.commit()
        return

    if result.get("success"):
        item.status = STATUS_SUCCESS
        item.validation_message = result.get("message")
        item.last_error = None
    else:
        item.status = STATUS_FAILED
        item.last_error = result.get("message")
    db.session.commit()


def execute_batch(batch: Batch, selected_item_ids: list, dry_run: bool = True, concurrency: int = None, current_user_id: str = None):
    """
    Execute (or dry-run) the selected items of a batch, honoring
    pause/resume/stop controls. Intended to be called from a background
    thread; the caller polls Batch/BatchItem status via the API.

    BUG FIX: same app-context issue as build_previews() above - each
    ThreadPoolExecutor worker now pushes its own app.app_context().
    `current_user_id` (the authenticated operator's userId, captured by
    the caller before handing off to a background thread since the
    session isn't available outside a request context) flows into every
    save so cnwriteoffby can be set correctly - see
    modification_service.build_modification_payload().
    """
    from flask import current_app
    app = current_app._get_current_object()
    concurrency = concurrency or settings.BULK_CONCURRENCY
    control = _get_control(batch.batch_id)
    control["paused"] = False
    control["stopped"] = False

    from datetime import datetime
    batch.status = "RUNNING"
    batch.started_at = datetime.utcnow()
    batch.dry_run = dry_run
    db.session.commit()
    log_audit(batch.batch_id, None, "EXECUTION_STARTED", f"dry_run={dry_run}, selected={len(selected_item_ids)}")

    def _work(item_id):
        # Respect pause: block (poll) until resumed or stopped.
        while control["paused"] and not control["stopped"]:
            time.sleep(0.5)
        if control["stopped"]:
            return
        with app.app_context():
            item = BatchItem.query.get(item_id)
            if item and item.can_retry() or (item and item.status == STATUS_READY):
                _execute_one(item, dry_run, current_user_id=current_user_id)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(_work, iid) for iid in selected_item_ids]
        for future in as_completed(futures):
            future.result()

    counts = summarize_counts(batch)
    batch.success_count = counts["success"]
    batch.failed_count = counts["failed"]
    batch.skipped_count = counts["skipped"]
    batch.already_applied_count = counts["already_applied"]
    batch.selected_gr = len(selected_item_ids)
    from datetime import datetime
    batch.finished_at = datetime.utcnow()
    batch.status = "STOPPED" if control["stopped"] else "COMPLETED"
    db.session.commit()
    log_audit(batch.batch_id, None, "EXECUTION_FINISHED", f"status={batch.status}, counts={counts}")


def retry_failed(batch: Batch, dry_run: bool = True, concurrency: int = None, current_user_id: str = None):
    failed_items = [i for i in batch.items.all() if i.status == STATUS_FAILED]
    execute_batch(batch, [i.id for i in failed_items], dry_run=dry_run, concurrency=concurrency, current_user_id=current_user_id)
