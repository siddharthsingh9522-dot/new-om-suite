"""
Shared, curated save-body construction for PUT /manual-cn/modification/{cn}
- used by BOTH services/modification_service.py (Billing Party) and
services/generic_modifier_service.py (Consignor, Consignee, Freight Mode,
Transport Mode), since all five modules write to the exact same upstream
endpoint and the endpoint's own quirks (which fields it accepts, the
cnwriteoffby/cnwriteoffDate behaviour) apply identically regardless of
which field a given module is changing. Centralized here so a future fix
only needs to happen once instead of drifting across two copies (which is
exactly how the cnwriteoffby/cnwriteoffDate fix was originally missed in
one of the two builders).

Confirmed from THREE independent real captures:
  - 24 Aug 2026, CN 1201264000015 (remark + billing party change)
  - 28 Aug 2026, CN 5935261001435 (transport mode change)
  - 30 Aug 2026, CN 2808261001345 (freight mode + billing party change)
"""
import re
from datetime import date

# Fields the real save UI sends back as-is, unchanged, confirmed across
# all three captures above. cnBillingPartyCode, cnFreightPaidMode and
# cnTptrMode are included here too since they pass through unchanged
# whenever a DIFFERENT field is the one being modified (e.g. a remark-only
# save still echoes back the CN's current freight mode untouched) - the
# calling module overwrites whichever ONE of these it is actually
# responsible for changing.
_SAVE_BODY_PASSTHROUGH_FIELDS = [
    "cnConsignorCode", "cnConsigneeCode", "cnBillingPartyCode",
    "cnDestinationBranchCode", "cnFreightPaidMode", "cnSourceBranchCode",
    "cnStatus", "cnTptrMode",
]


def reformat_cn_date(raw_value):
    """
    GET returns cnCnDate like "2026-07-18 17:33:19.401000" (space
    separator, microseconds). The real save UI sends it back as
    "2026-07-18T17:33:00" (ISO 'T' separator, seconds zeroed, no
    microseconds) - confirmed from three real captured Network requests.
    """
    if not raw_value or not isinstance(raw_value, str):
        return raw_value
    match = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})", raw_value)
    if not match:
        return raw_value
    date_part, hour, minute = match.groups()
    return f"{date_part}T{hour}:{minute}:00"


def build_curated_save_body(existing_data: dict, final_remark: str, current_user_id: str = None, overrides: dict = None) -> dict:
    """
    Build the common part of the save body every module shares. The
    caller then overlays whichever ONE field it's actually responsible
    for changing (cnBillingPartyCode/Name, cnConsignorCode/Name,
    cnConsigneeCode/Name, cnFreightPaidMode, or cnTptrMode) - and may
    optionally overlay a second field too (e.g. the Freight Mode
    billing-party suggestion, once the user has explicitly accepted it).

    Confirmed transformations - see this module's docstring for the three
    real captures backing each one:
      - cnNo is NEVER in the body - it only appears in the URL path.
      - cnConsignorName / cnConsigneeName / cnBillingPartyName are dropped
        UNLESS a module explicitly needs to set one as part of its own
        change (the caller adds it back in that case).
      - enterFormName, cnCofRemarks, cnBillNo, billingLocation,
        billingBranchCode, cnTransitStatus, cnModifiedBy, cnModifiedDate,
        billingStatus, currentBranchCode are all dropped.
      - cnCnDate is reformatted (see reformat_cn_date).
      - Every EXISTING invoice's "isNew" is sent as false.
      - cnDeliveryDate is preserved from the original record (not forced
        to null) - spot-checked against the live Docket Query screen with
        no visible data loss.
      - manualCnNo / cnMamualCnDate are EXCLUDED BY DEFAULT (not just
        passed through as null). Separate real-world testing on this
        project found upstream sometimes rejects the save with
        "Manual CN No already used in another CN: <number>" when this is
        echoed back as null - a real upstream quirk. If the operator
        explicitly sets these via editable fields, pass them via
        `overrides`.
      - cnwriteoffby: set to current_user_id ONLY if the original value is
        null/empty; otherwise the existing value is preserved. Confirmed
        by the 28 Aug and 30 Aug captures both showing an originally-null
        value become the acting user's id after save.
      - cnwriteoffDate: always TODAY'S DATE at save time, confirmed
        identical across all three captures (each showed that day's own
        date, regardless of what the original value was).
      - cnwriteoffRemarks: preserved if present, else sent as "" (not
        null).
    """
    overrides = overrides or {}
    body = {field: existing_data.get(field) for field in _SAVE_BODY_PASSTHROUGH_FIELDS}
    body["cnCnDate"] = reformat_cn_date(existing_data.get("cnCnDate"))
    body["cnDeliveryDate"] = existing_data.get("cnDeliveryDate")
    body["cnRemarks"] = final_remark

    if overrides.get("manualCnNo"):
        body["manualCnNo"] = overrides["manualCnNo"]
    if overrides.get("cnMamualCnDate"):
        body["cnMamualCnDate"] = overrides["cnMamualCnDate"]

    existing_writeoffby = existing_data.get("cnwriteoffby")
    body["cnwriteoffby"] = existing_writeoffby if existing_writeoffby else current_user_id
    body["cnwriteoffDate"] = date.today().isoformat()
    body["cnwriteoffRemarks"] = existing_data.get("cnwriteoffRemarks") or ""

    invoices = existing_data.get("invoices") or []
    body["invoices"] = [{**invoice, "isNew": False} for invoice in invoices]

    return body
