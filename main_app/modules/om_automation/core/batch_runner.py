# ==========================================
# OM Automation V2
# core/batch_runner.py
#
# Single source of truth for "run this Excel file
# through this API, in parallel, with progress/log
# callbacks". Used by both the desktop GUI
# (gui/pages.py) and the web app (web_app.py) so the
# batch logic only exists in one place.
# ==========================================

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

from modules.om_automation.config import MAX_WORKERS, GSTIN_HEADERS, PARTY_HEADERS

from modules.om_automation.excel.reader import ExcelReader
from modules.om_automation.excel.generic_reader import GenericReader

from modules.om_automation.core.validator import validator
from modules.om_automation.core.processor import Processor

from modules.om_automation.api.cn_api import cn_api
from modules.om_automation.api.gst_api import gst_api
from modules.om_automation.api.customer_api import customer_api


def _run_batch(records, get_key, fetch_fn, row_seed, progress_cb, log_cb, stop_event):
    """
    records   : list of dicts (from ExcelReader / GenericReader)
    get_key   : fn(record) -> the value to fetch (cn / gstin / party code)
    fetch_fn  : fn(key) -> {"success", "message", "data"}
    row_seed  : fn(record) -> base dict with Input Sheet/Row/Column/<label>
    """

    total = len(records)
    success_rows, error_rows = [], []

    def worker(record):

        row = row_seed(record)
        key = get_key(record)

        valid, reason = validator.validate(key)
        if not valid:
            return False, {**row, "Error": reason}

        result = fetch_fn(key)

        if not result["success"]:
            return False, {**row, "Error": result["message"]}

        row.update(result["data"])
        return True, row

    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

        futures = {}

        for record in records:

            if stop_event.is_set():
                break

            futures[executor.submit(worker, record)] = record

        for future in as_completed(futures):

            completed += 1
            ok, row = future.result()

            label = row.get("CN") or row.get("GSTIN") or row.get("Party Code") or ""

            if ok:
                success_rows.append(row)
                log_cb(f"[{completed}/{total}] OK  : {label}")
            else:
                error_rows.append(row)
                log_cb(f"[{completed}/{total}] FAIL: {label} - {row.get('Error')}")

            progress_cb(completed, total)

            if stop_event.is_set():
                break

    return success_rows, error_rows


def run_cn_batch(file, progress_cb, log_cb, stop_event):

    records = ExcelReader(file).read()

    def row_seed(r):
        return {
            "Input Sheet": r["sheet"],
            "Input Row": r["row"],
            "Input Column": r["column"],
            "CN": r["cn"]
        }

    return _run_batch(
        records, lambda r: r["cn"], cn_api.fetch, row_seed,
        progress_cb, log_cb, stop_event
    )


def run_gst_batch(file, progress_cb, log_cb, stop_event):

    records = GenericReader(file, GSTIN_HEADERS, label="GSTIN").read()

    def row_seed(r):
        return {
            "Input Sheet": r["sheet"],
            "Input Row": r["row"],
            "Input Column": r["column"],
            "GSTIN": r["value"]
        }

    return _run_batch(
        records, lambda r: r["value"], gst_api.fetch, row_seed,
        progress_cb, log_cb, stop_event
    )


def run_party_batch(file, progress_cb, log_cb, stop_event):

    records = GenericReader(file, PARTY_HEADERS, label="Party Code").read()

    def row_seed(r):
        return {
            "Input Sheet": r["sheet"],
            "Input Row": r["row"],
            "Input Column": r["column"],
            "Party Code": r["value"]
        }

    return _run_batch(
        records, lambda r: r["value"], customer_api.fetch, row_seed,
        progress_cb, log_cb, stop_event
    )


def run_master_batch(file, progress_cb, log_cb, stop_event):

    records = ExcelReader(file).read()
    total = len(records)

    success_rows, error_rows = [], []
    completed = 0

    processor = Processor()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

        futures = {}

        for record in records:

            if stop_event.is_set():
                break

            futures[executor.submit(processor.process_record, record)] = record

        for future in as_completed(futures):

            completed += 1
            result = future.result()

            if result["success"]:
                success_rows.append(result["data"])
                log_cb(f"[{completed}/{total}] OK  : {result['data'].get('CN')}")
            else:
                error_rows.append(result["error"])
                log_cb(
                    f"[{completed}/{total}] FAIL: {result['error'].get('CN')} "
                    f"- {result['error'].get('Error')}"
                )

            progress_cb(completed, total)

            if stop_event.is_set():
                break

    return success_rows, error_rows


def run_master_manual(value):

    processor = Processor()

    record = {
        "sheet": "Manual",
        "row": 0,
        "column": "Manual",
        "cn": value
    }

    return processor.process_record(record)


# Lookup tables used by both the desktop pages and the web routes.

MANUAL_FETCHERS = {
    "cn": cn_api.fetch,
    "gst": gst_api.fetch,
    "party": customer_api.fetch,
}

BATCH_RUNNERS = {
    "cn": run_cn_batch,
    "gst": run_gst_batch,
    "party": run_party_batch,
    "master": run_master_batch,
}
