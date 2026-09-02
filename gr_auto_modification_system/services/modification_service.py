"""
Core modification logic:

 - build_record_preview(): fetch CN + party, apply remark-merge rules,
   and return a fully-described preview row (status, messages, values).
 - build_modification_payload(): assemble the payload that WOULD be sent
   to the real save/update API, preserving all existing CN data. Delegates
   the shared curated-field logic to services/save_payload_builder.py.
 - save_modification(): isolated call-site for the actual save API.
"""
import logging

from config import settings
from services.cn_service import fetch_cn_details, CNNotFoundError, CNLookupError
from services.party_service import fetch_party_details, PartyNotFoundError, PartyLookupError
from services.api_client import api_client
from services.save_payload_builder import build_curated_save_body
from utils.remark_parser import extract_party_code, build_final_remark, normalize_text
from utils.retry import PermanentAPIError, TemporaryAPIError

logger = logging.getLogger("gr_auto_mod.modification_service")

STATUS_READY = "READY"
STATUS_ALREADY_APPLIED = "ALREADY_APPLIED"
STATUS_INVALID_CN = "INVALID_CN"
STATUS_INVALID_PARTY = "INVALID_PARTY"
STATUS_ERROR = "ERROR"


def build_record_preview(gr_number: str, new_remark: str, manual_party_code: str = None) -> dict:
    """
    Build a complete before/after preview for a single GR/CN record.

    This function NEVER modifies anything - it is read-only against the
    upstream API (fetch_cn_details / fetch_party_details only).
    """
    result = {
        "gr_number": gr_number,
        "existing_party_code": None,
        "new_party_code": None,
        "party_name": None,
        "billing_location": None,
        "existing_remark": None,
        "new_remark": normalize_text(new_remark),
        "final_remark": None,
        "party_detection_method": None,
        "status": STATUS_ERROR,
        "message": "",
        "cn_snapshot": None,
        "party_snapshot": None,
    }

    # 1. Fetch existing CN details
    try:
        cn_data = fetch_cn_details(gr_number)
    except CNNotFoundError as exc:
        result["status"] = STATUS_INVALID_CN
        result["message"] = str(exc)
        return result
    except CNLookupError as exc:
        result["status"] = STATUS_ERROR
        result["message"] = f"Could not reach upstream for CN lookup: {exc}"
        return result

    result["cn_snapshot"] = cn_data
    result["existing_party_code"] = cn_data.get("cnBillingPartyCode")
    result["existing_remark"] = cn_data.get("cnRemarks")

    # 2. Determine party code (auto-detect, or fall back to manual input)
    party_code = manual_party_code
    method = "manual"
    if not party_code:
        party_code, method = extract_party_code(new_remark)

    if not party_code:
        result["status"] = STATUS_INVALID_PARTY
        result["message"] = "Party Code could not be automatically detected. Please provide it manually."
        result["party_detection_method"] = method
        return result

    result["new_party_code"] = party_code
    result["party_detection_method"] = method

    # 3. Validate party
    try:
        party_data = fetch_party_details(party_code)
    except PartyNotFoundError as exc:
        result["status"] = STATUS_INVALID_PARTY
        result["message"] = str(exc)
        return result
    except PartyLookupError as exc:
        result["status"] = STATUS_ERROR
        result["message"] = f"Could not reach upstream for party validation: {exc}"
        return result

    result["party_snapshot"] = party_data
    result["party_name"] = party_data.get("customerCustomerName")
    result["billing_location"] = party_data.get("branchBranchName")

    # 4. Build final remark with duplicate protection
    final_remark, action = build_final_remark(cn_data.get("cnRemarks"), new_remark)
    result["final_remark"] = final_remark

    if action == STATUS_ALREADY_APPLIED:
        result["status"] = STATUS_ALREADY_APPLIED
        result["message"] = "This remark has already been applied to this GR/CN. Skipping to avoid duplication."
    else:
        result["status"] = STATUS_READY
        result["message"] = "Ready to modify."

    return result


# Fields the real save UI sends back as-is, unchanged, confirmed from a
# real captured PUT /manual-cn/modification/{cn_no} Network request
# (24 Aug 2026, CN 1201264000015). manualCnNo/cnMamualCnDate/cnwriteoffby/
# cnwriteoffDate/cnwriteoffRemarks are handled separately below, NOT via
# this simple passthrough list - see build_modification_payload()'s
# docstring for why each of those needs special handling.
def build_modification_payload(existing_data: dict, party_data: dict, final_remark: str, overrides: dict = None, current_user_id: str = None) -> dict:
    """
    Build the exact save/modification PUT body for a Billing Party change.
    Delegates the shared curated-field logic to
    services/save_payload_builder.py (see that module's docstring for the
    full evidence trail) and overlays this module's own field:
    cnBillingPartyCode. cnBillingPartyName is deliberately NOT sent -
    confirmed dropped from the real captured PUT body (the *Name fields
    are display-only, resolved server-side from the code).
    """
    body = build_curated_save_body(existing_data, final_remark, current_user_id=current_user_id, overrides=overrides)
    body["cnBillingPartyCode"] = party_data.get("customerCustomerCode")

    return {
        "cnNo": existing_data.get("cnNo"),
        "save_body": body,
        "changes": {
            "cnRemarks": final_remark,
            "cnBillingPartyCode": party_data.get("customerCustomerCode"),
        },
    }


def save_modification(gr_number: str, payload: dict) -> dict:
    """
    Isolated call-site for the actual save/update API.

    The request body sent is `payload["save_body"]` - the curated field
    set confirmed from two real captured Network requests (see
    build_modification_payload()'s docstring for exactly what's included,
    excluded, and why).
    """
    if not settings.save_api_ready():
        return {
            "success": False,
            "configured": False,
            "message": (
                "Save API is not configured yet. Preview completed successfully; "
                "no data has been modified."
            ),
        }

    body = payload.get("save_body") if isinstance(payload, dict) and "save_body" in payload else payload

    # BUG FIX: SAVE_API_URL is a template ("/manual-cn/modification/{cn_no}")
    # but was being sent to api_client verbatim, with the literal
    # "{cn_no}" text never substituted for the real CN number - every
    # real save via this function would have been rejected outright by
    # the real API (this path doesn't exist). gr_number is the CN number
    # this whole function is already scoped to, so this is a pure
    # "forgot to call .format()" bug, not a design gap.
    url_template = settings.SAVE_API_URL
    path = url_template.format(cn_no=gr_number) if "{cn_no}" in url_template else url_template

    try:
        response = api_client.send(settings.SAVE_API_METHOD, path, body)
    except PermanentAPIError as exc:
        return {"success": False, "configured": True, "message": f"Save rejected by upstream: {exc}"}
    except TemporaryAPIError as exc:
        return {"success": False, "configured": True, "message": f"Save failed (temporary): {exc}"}

    # Never assume success just because the request didn't raise - require
    # an explicit success indicator from the upstream response.
    if isinstance(response, dict) and response.get("status") == "success":
        return {"success": True, "configured": True, "message": "Modification saved successfully.", "response": response}

    return {
        "success": False,
        "configured": True,
        "message": "Save API responded, but did not confirm success.",
        "response": response,
    }
