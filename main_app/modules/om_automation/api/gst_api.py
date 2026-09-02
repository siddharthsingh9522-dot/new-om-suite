# ==========================================
# OM Automation V2
# api/gst_api.py
# ==========================================

from modules.om_automation.api.session import http
from modules.om_automation.config import GST_API, GST_HEADERS

import threading
import time
import traceback
import requests

# The GST portal search endpoint is the most rate-limit/bot-protection
# sensitive call in the whole pipeline - hammering it with the same
# concurrency as the other APIs (MAX_WORKERS, often 20) gets later
# calls in a batch blocked. Cap it independently of whatever worker
# pool size the caller (processor / batch_runner) uses.
_GST_SLOTS = threading.Semaphore(2)
_GST_DELAY_SECONDS = 1.5


class GSTAPI:

    def __init__(self):
        pass

    def fetch(self, gstin):

        if gstin is None or str(gstin).strip() == "":
            return {
                "success": False,
                "message": "GSTIN Missing",
                "data": None
            }

        with _GST_SLOTS:
            time.sleep(_GST_DELAY_SECONDS)

            try:
                payload = {"gstin": str(gstin).strip()}

                try:
                    response = http.post(GST_API, json=payload, headers=GST_HEADERS)

                except requests.exceptions.RequestException as e:
                    return {
                        "success": False,
                        "message": f"Network Error: {e}",
                        "data": None
                    }

                if response.status_code != 200:
                    return {
                        "success": False,
                        "message": f"HTTP {response.status_code}",
                        "data": None
                    }

                try:
                    obj = response.json()
                except Exception:
                    return {
                        "success": False,
                        "message": "Invalid JSON",
                        "data": None
                    }

                # A 200 response doesn't guarantee a real record - the
                # portal can return 200 with an error payload (invalid
                # GSTIN, blocked/rate-limited request, etc).
                if not obj.get("gstin"):
                    return {
                        "success": False,
                        "message": f"GST lookup failed: {obj}",
                        "data": None
                    }

                result = {
                    "GSTIN": obj.get("gstin"),
                    "Trade Name": obj.get("tradeNam"),
                    "Legal Name": obj.get("lgnm"),
                    "GST Status": obj.get("sts"),
                    "Registration Date": obj.get("rgdt"),
                    "Taxpayer Type": obj.get("dty"),
                    "Business Type": obj.get("ctb"),
                    "State Jurisdiction": obj.get("stj"),
                    "Central Jurisdiction": obj.get("ctj"),
                    "Nature Of Business": ", ".join(obj.get("nba", []) or []),
                    # Named "GST Address" (not "Address") so it doesn't
                    # overwrite the customer table's own Address field
                    # when both dicts get merged into the same row.
                    "GST Address": obj.get("pradr", {}).get("adr") if obj.get("pradr") else None,
                    "E-Invoice": obj.get("einvoiceStatus"),
                    "EKYC": obj.get("ekycVFlag"),
                }

                return {
                    "success": True,
                    "message": "Success",
                    "data": result
                }

            except Exception as e:
                traceback.print_exc()
                return {
                    "success": False,
                    "message": str(e),
                    "data": None
                }


gst_api = GSTAPI()
