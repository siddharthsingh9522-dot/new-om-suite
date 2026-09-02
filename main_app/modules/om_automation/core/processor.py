# ==========================================
# OM Automation V2
# core/processor.py
# ==========================================

import time

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

from modules.om_automation.config import MAX_WORKERS

from modules.om_automation.excel.reader import ExcelReader

from modules.om_automation.api.cn_api import cn_api
from modules.om_automation.api.customer_api import customer_api
from modules.om_automation.api.gst_api import gst_api

from modules.om_automation.core.validator import validator
from modules.om_automation.core.cache import customer_cache, gst_cache


class Processor:

    def __init__(self):
        self.success = []
        self.errors = []
        self.summary = {
            "Total": 0,
            "Success": 0,
            "Failed": 0
        }

    def process_file(
        self,
        excel_file,
        progress=None,
        logger=None,
        control=None
    ):
        """
        control: optional object (see core.worker.WorkerControl)
        exposing should_stop() and wait_if_paused(), used so a
        running GUI Worker can pause/stop a batch in progress.
        """

        reader = ExcelReader(excel_file)
        records = reader.read()

        self.summary["Total"] = len(records)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

            futures = {}

            for record in records:

                if control is not None:
                    control.wait_if_paused()

                    if control.should_stop():
                        break

                futures[executor.submit(self.process_record, record)] = record

            completed = 0
            total = len(futures)

            for future in as_completed(futures):

                completed += 1
                result = future.result()

                if result["success"]:
                    self.success.append(result["data"])
                    self.summary["Success"] += 1
                else:
                    self.errors.append(result["error"])
                    self.summary["Failed"] += 1

                if logger:
                    logger(completed, total, result)

                if progress:
                    progress(completed, total)

                if control is not None and control.should_stop():
                    break

        return {
            "success": self.success,
            "errors": self.errors,
            "summary": self.summary
        }

    def process_record(self, record):

        row = {
            "Input Sheet": record["sheet"],
            "Input Row": record["row"],
            "Input Column": record["column"],
            "CN": record["cn"]
        }

        try:
            valid, reason = validator.validate(record["cn"])

            if not valid:
                return {
                    "success": False,
                    "error": {
                        **row,
                        "API Status": "Skipped",
                        "Error": reason
                    }
                }

            cn_result = cn_api.fetch(record["cn"])

            if not cn_result["success"]:
                return {
                    "success": False,
                    "error": {
                        **row,
                        "API Status": "CN API Failed",
                        "Error": cn_result["message"]
                    }
                }

            row.update(cn_result["data"])
            row["API Status"] = "Success"
            row["Pipeline Stage"] = "CN Success"

            party = row.get("Party Code")

            if party:

                cached = customer_cache.get(party)

                if cached is not None:
                    customer = cached
                else:
                    customer = customer_api.fetch(party)
                    customer_cache.set(party, customer)

                if customer["success"]:
                    row.update(customer["data"])
                    row["Pipeline Stage"] = "Customer Found"

            # The GSTIN to verify comes from the customer record's
            # "GST" field (set by customer_api.fetch above), not from
            # the CN API response - the CN payload never carries it.
            gst = row.get("GST")

            if gst:

                cached_gst = gst_cache.get(gst)

                if cached_gst is not None:
                    gst_data = cached_gst
                else:
                    gst_data = gst_api.fetch(gst)
                    gst_cache.set(gst, gst_data)

                if gst_data["success"]:
                    row.update(gst_data["data"])
                    row["Pipeline Stage"] = "GST Verified"

            return {
                "success": True,
                "data": row
            }

        except Exception as e:
            return {
                "success": False,
                "error": {
                    **row,
                    "API Status": "Exception",
                    "Error": str(e)
                }
            }
