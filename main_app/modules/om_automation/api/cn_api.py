# ==========================================
# OM Automation V2
# api/cn_api.py
# ==========================================

from modules.om_automation.api.session import http
from modules.om_automation.config import CN_API

import traceback
import requests


class CNApi:

    def __init__(self):
        pass

    def fetch(self, cn):
        """
        Fetch CN Details

        Returns
        {
            success : True/False
            message : ""
            data : {}
        }

        Field mapping below is the VERIFIED shape of this endpoint
        (load.omone.in/utility-service/api/cn-status/{cn}), confirmed
        against a known-working pipeline hitting the same URL. Do not
        guess new keys here without checking a real response first -
        wrong keys silently return None instead of erroring, which is
        what caused most columns (Party Code, GSTIN, freight/billing
        detail) to come back empty.
        """

        try:
            url = CN_API.format(cn)

            try:
                response = http.get(url)

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
                json_data = response.json()
            except Exception:
                return {
                    "success": False,
                    "message": "Invalid JSON Response",
                    "data": None
                }

            if json_data is None:
                return {
                    "success": False,
                    "message": "Empty Response",
                    "data": None
                }

            if json_data.get("status") != "success":
                return {
                    "success": False,
                    "message": json_data.get("message", "CN Not Found"),
                    "data": None
                }

            data = json_data.get("data")

            if data is None:
                return {
                    "success": False,
                    "message": "Missing Data",
                    "data": None
                }

            main = data.get("main", {}) or {}
            freight = data.get("freight", {}) or {}

            bill = {}
            bill_freight_list = data.get("billFreight", []) or []
            if len(bill_freight_list) > 0:
                bill = bill_freight_list[0] or {}

            # "Party Code"/"Party Name" are not separate fields on the
            # CN payload - they're packed into billingParty as
            # "<code>-<name>", same as the party code embedded in
            # Consignor/Consignee. Split it exactly like the proven
            # pipeline does, or Party Code silently comes out empty
            # and the Customer/GST lookups below it never fire.
            billing_party = main.get("billingParty") or ""
            party_code = billing_party.split("-")[0] if billing_party else None
            party_name = "-".join(billing_party.split("-")[1:]) if billing_party else None

            Source_Branch = main.get("source") or "chSource"
            Source_code = Source_Branch.split("-")[0] if Source_Branch else None
            Source_Branch = "-".join(Source_Branch.split("-")[1:]) if Source_Branch else None

            # "Destination" follows the same "<code>-<name>" packing as
            # SourceBranch/Consignor/Consignee - split it the same way
            # instead of dumping the raw combined string into one column.
            Destination = main.get("destination") or ""
            Destination_code = Destination.split("-")[0] if Destination else None
            Destination_Branch = "-".join(Destination.split("-")[1:]) if Destination else None

            Consignor = main.get("consignor") or ""
            Consignor_code = Consignor.split("-")[0] if Consignor else None
            Consignor_name = "-".join(Consignor.split("-")[1:]) if Consignor else None

            Consignee = main.get("consignee") or ""
            Consignee_code = Consignee.split("-")[0] if Consignee else None
            Consignee_name = "-".join(Consignee.split("-")[1:]) if Consignee else None

            result = {
                # CN is the value we queried with, not a field the API
                # echoes back under a predictable key - use the input.
                "CN": cn,
                "CN Date": main.get("cnDate"),
                # UNVERIFIED KEY - "Remarks" (capital R, no camelCase)
                # breaks the camelCase pattern every other confirmed
                # field follows (cnDate, currentStatus, bookingMode...).
                # Trying common variants as a fallback until confirmed
                # against a real raw response.
                "Remarks": main.get("remarks") or main.get("remarks") or main.get("Remark") or main.get("remark"),
                "Party Code": party_code,
                "Party Name": party_name,
                # NOTE: keys below must match REPORT_COLUMNS in config.py
                # EXACTLY (including case) - the report builder looks
                # these up by name, and a case mismatch silently returns
                # an empty column instead of erroring.
                "Source Code": Source_code,
                "Source Branch": Source_Branch,
                "Destination Code": Destination_code,
                "Destination Branch": Destination_Branch,
                "Consignor Code": Consignor_code,
                "Consignor Name": Consignor_name,
                "Consignee Code": Consignee_code,
                "Consignee Name": Consignee_name,
                "CN Status": main.get("currentStatus"),
                "Booking Mode": main.get("bookingMode"),
                "Freight Mode": main.get("freightMode"),
                "Gross Value": main.get("grossValue"),
                "Net Value": main.get("netValue"),
                "Charged Weight": main.get("chargedWeight"),
                "Actual Weight": main.get("actualWeight"),
                "Freight Total": main.get("freightTotal"),
                "Rate Per KG": freight.get("cnRatePerKg"),
                "FOV": freight.get("cnFov"),
                # UNVERIFIED KEY - "DDR No" with a literal space is a
                # very unusual raw JSON key (nothing else in this
                # payload has a space in its key). Trying common
                # variants as a fallback until confirmed against a
                # real raw response.
                # FIX: `data` is a dict, not a function - `data("DDRNo")`
                # was calling the dict, which raises
                # "TypeError: 'dict' object is not callable" and gets
                # caught by the outer except, masking real errors.
                # Also use .get() throughout so a missing "ddr" key
                # doesn't raise KeyError either.
                "DDR No": (
                    (data.get("ddr") or {}).get("outDdrNo")
                    or data.get("DDRNo")
                    or data.get("ddrNo")
                    or data.get("DDR_No")
                    or data.get("ddr_no")
                    or data.get("ddrno")
                ),
                # BEST-EFFORT / UNVERIFIED: package count isn't part of
                # the confirmed field set (unlike everything else in
                # this dict). Tries a couple of likely key names but
                # may legitimately come back None on the live API -
                # the UI should show that as "-", not treat it as a bug.
                # (Single definition only - a duplicate "Package" key
                # further down used to silently overwrite this fallback
                # chain with just freight.get("package"). Removed.)
                "Package": freight.get("tpkgNo") or freight.get("pkg") or main.get("pkg"),
                "Bill No": bill.get("billNo"),
                "Bill Date": bill.get("billDate"),
                "Lorry No": main.get("lorryNo"),
                "Delivery Date": main.get("deliveryDate"),
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


cn_api = CNApi()
