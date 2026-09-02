"""
Generic modifier engine shared by the four NEW modules (Consignor,
Consignee, Freight Mode, Transport Mode). The ORIGINAL Billing Party module
keeps using its own dedicated services/modification_service.py untouched -
this file never replaces or is called by that one.

Mirrors the same design as services/modification_service.py:
 - build_record_preview_generic(): read-only, fetch + compute what WOULD change
 - build_modification_payload_generic(): assemble the save payload, preserving
   all existing CN data except fields known to cause upstream problems
 - save_modification_generic(): isolated save call-site, never claims success
   without an explicit upstream confirmation
 - verify_after_save_generic(): re-fetch after a save and compare expected vs
   actual, so a 200-OK response is never blindly trusted
"""
import logging

from config import settings
from config.modules_config import get_module
from services.cn_service import fetch_cn_details, CNNotFoundError, CNLookupError
from services.party_service import fetch_party_details, PartyNotFoundError, PartyLookupError
from services.api_client import api_client
from services.save_payload_builder import build_curated_save_body
from utils.remark_parser import build_final_remark, normalize_text
from utils.retry import PermanentAPIError, TemporaryAPIError

logger = logging.getLogger("gr_auto_mod.generic_modifier_service")

STATUS_READY = "READY"
STATUS_ALREADY_APPLIED = "ALREADY_APPLIED"
STATUS_INVALID_CN = "INVALID_CN"
STATUS_INVALID_VALUE = "INVALID_VALUE"
STATUS_ERROR = "ERROR"

CHANGE_TYPE_VALUE_ONLY = "VALUE_ONLY"
CHANGE_TYPE_REMARK_ONLY = "REMARK_ONLY"
CHANGE_TYPE_VALUE_AND_REMARK = "VALUE_AND_REMARK"
CHANGE_TYPE_NO_CHANGE = "NO_CHANGE"

MODULE_FREIGHT_MODE = "freight_mode"
# Confirmed codes - see config/mode_mappings.py (manually verified 29 Aug 2026).
FREIGHT_MODE_PREPAID = 1
FREIGHT_MODE_TO_PAY = 2


def _label_for_dropdown_value(module: dict, value: str):
    if value is None:
        return None
    for option in module.get("options", []):
        if str(option.get("value")) == str(value):
            return option.get("label")
    return str(value)  # unmapped raw value - shown as-is, never invented


def build_record_preview_generic(module_key: str, gr_number: str, new_value, new_remark: str) -> dict:
    """
    Build a complete before/after preview for a single GR/CN record, for
    any of the four generic-engine modules. Read-only against upstream.

    `new_value` may be None/blank - meaning no value change was requested
    for this record, only a remark change (this mirrors the "optional new
    code" wording in the spec for Consignor/Consignee).
    """
    module = get_module(module_key)
    new_value = (str(new_value).strip() if new_value not in (None, "") else None)

    result = {
        "gr_number": gr_number,
        "module_key": module_key,
        "existing_value": None,
        "new_value": new_value,
        "existing_value_label": None,
        "new_value_label": None,
        "existing_remark": None,
        "new_remark": normalize_text(new_remark),
        "final_remark": None,
        "status": STATUS_ERROR,
        "message": "",
        "change_type": CHANGE_TYPE_NO_CHANGE,
        "value_changed": False,
        "remark_changed": False,
        "cn_snapshot": None,
        "value_snapshot": None,
        "billing_party_suggestion": None,
    }

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

    if module["kind"] == "code":
        existing_value = cn_data.get(module["current_code_field"])
        result["existing_value"] = existing_value
        result["existing_value_label"] = cn_data.get(module["current_name_field"])

        effective_new_value = new_value if new_value is not None else (
            str(existing_value) if existing_value is not None else None
        )
        value_changed = (
            new_value is not None
            and str(existing_value) != str(new_value)
        )

        if value_changed:
            try:
                value_data = fetch_party_details(new_value)
            except PartyNotFoundError as exc:
                result["status"] = STATUS_INVALID_VALUE
                result["message"] = str(exc)
                return result
            except PartyLookupError as exc:
                result["status"] = STATUS_ERROR
                result["message"] = f"Could not reach upstream for {module['value_label']} validation: {exc}"
                return result

            result["value_snapshot"] = value_data
            result["new_value_label"] = value_data.get("customerCustomerName")
        else:
            result["new_value_label"] = result["existing_value_label"]

        result["new_value"] = effective_new_value

    else:  # "dropdown" kind - freight mode / transport mode
        existing_value = cn_data.get(module["current_value_field"])
        result["existing_value"] = existing_value
        result["existing_value_label"] = _label_for_dropdown_value(module, existing_value)

        effective_new_value = new_value if new_value is not None else existing_value
        value_changed = (
            new_value is not None
            and str(existing_value) != str(new_value)
        )
        result["new_value"] = effective_new_value
        result["new_value_label"] = _label_for_dropdown_value(module, effective_new_value)

    # Remark merge - identical rule to Billing Party: new remark prepended
    # before old, with duplicate protection.
    final_remark, remark_action = build_final_remark(cn_data.get("cnRemarks"), new_remark)
    result["existing_remark"] = cn_data.get("cnRemarks")
    result["final_remark"] = final_remark
    remark_changed = remark_action != STATUS_ALREADY_APPLIED

    result["value_changed"] = value_changed
    result["remark_changed"] = remark_changed

    if not value_changed and not remark_changed:
        result["status"] = STATUS_ALREADY_APPLIED
        result["change_type"] = CHANGE_TYPE_NO_CHANGE
        result["message"] = "Nothing to change - value and remark both already match."
    else:
        result["status"] = STATUS_READY
        if value_changed and remark_changed:
            result["change_type"] = CHANGE_TYPE_VALUE_AND_REMARK
        elif value_changed:
            result["change_type"] = CHANGE_TYPE_VALUE_ONLY
        else:
            result["change_type"] = CHANGE_TYPE_REMARK_ONLY
        result["message"] = "Ready to modify."

    if module_key == MODULE_FREIGHT_MODE and value_changed:
        result["billing_party_suggestion"] = _freight_mode_billing_suggestion(
            cn_data, effective_new_value
        )

    return result


def _freight_mode_billing_suggestion(cn_data: dict, new_freight_value: str):
    """
    PREPAID<->TO PAY is the one Freight Mode transition with a known real
    business convention: a real captured save (30 Aug 2026, CN
    2808261001345) showed Billing Party moving from Consignor to Consignee
    together with a PREPAID->TO PAY change. Directly asking the operator
    who made that change confirmed the real system does NOT do this
    automatically - they typed the new Party Code themselves, applying
    their own business judgement. So this is offered here ONLY as an
    opt-in suggestion (see the "apply_billing_suggestion" flag in
    routes/modules.py's single_confirm) - never applied silently, since
    the real system itself doesn't do that either.

    Returns None if the transition isn't PREPAID<->TO PAY, or if the
    suggested party already matches the current Billing Party (nothing
    useful to suggest).
    """
    try:
        new_code = int(new_freight_value)
    except (TypeError, ValueError):
        return None

    if new_code == FREIGHT_MODE_TO_PAY:
        suggested_code = cn_data.get("cnConsigneeCode")
        suggested_name = cn_data.get("cnConsigneeName")
        reason = (
            "TO PAY freight is typically collected at delivery, so billing "
            "responsibility commonly shifts to the Consignee (receiver)."
        )
    elif new_code == FREIGHT_MODE_PREPAID:
        suggested_code = cn_data.get("cnConsignorCode")
        suggested_name = cn_data.get("cnConsignorName")
        reason = (
            "PREPAID freight is typically paid at booking, so billing "
            "responsibility commonly stays with the Consignor (sender)."
        )
    else:
        return None

    if suggested_code is None:
        return None
    if str(suggested_code) == str(cn_data.get("cnBillingPartyCode")):
        return None  # already matches - nothing to suggest

    return {
        "code": suggested_code,
        "name": suggested_name,
        "current_billing_party_code": cn_data.get("cnBillingPartyCode"),
        "current_billing_party_name": cn_data.get("cnBillingPartyName"),
        "reason": reason,
    }


def build_modification_payload_generic(module_key: str, existing_data: dict, new_value, new_value_label, final_remark: str, current_user_id: str = None, billing_party_override: dict = None) -> dict:
    """
    Build the payload that WOULD be sent to the real save/modification API
    for this module. Delegates the shared curated-field logic to
    services/save_payload_builder.py (see that module's docstring for the
    full evidence trail across three real captures) and overlays only
    this module's own field.

    For "code" kind modules (Consignor, Consignee), only the *Code* field
    is sent - confirmed from a real capture that cnConsignorName/
    cnConsigneeName/cnBillingPartyName are ALL dropped from the real PUT
    body, not just the billing-party one; the *_name_field in
    config/modules_config.py is used for display purposes only.

    `billing_party_override` is the Freight-Mode-only "suggested billing
    party" feature (see build_record_preview_generic) - only applied when
    the operator has explicitly accepted the suggestion, never silently.
    Real evidence (30 Aug 2026 capture, CN 2808261001345) shows a human
    operator manually chose to also change Billing Party when switching
    Freight Mode between PREPAID/TO PAY - the real system does NOT do
    this automatically, so this app doesn't either; it only ever offers
    it as an opt-in suggestion.
    """
    module = get_module(module_key)
    body = build_curated_save_body(existing_data, final_remark, current_user_id=current_user_id)

    changes = {"cnRemarks": final_remark}

    if module["kind"] == "code":
        body[module["write_code_field"]] = new_value
        changes[module["write_code_field"]] = new_value
    else:
        body[module["write_value_field"]] = new_value
        changes[module["write_value_field"]] = new_value

    if billing_party_override:
        body["cnBillingPartyCode"] = billing_party_override["code"]
        changes["cnBillingPartyCode"] = billing_party_override["code"]

    return {
        "cnNo": existing_data.get("cnNo"),
        "module_key": module_key,
        "save_body": body,
        "changes": changes,
    }


def save_modification_generic(module_key: str, gr_number: str, payload: dict) -> dict:
    """
    Isolated save call-site, shared by all generic-engine modules. Same
    unconfigured-by-default behaviour as services.modification_service -
    never claims success without the real endpoint confirming it.
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

    try:
        # Same URL-template fix as services/modification_service.py -
        # SAVE_API_URL's "{cn_no}" placeholder was never being substituted.
        url_template = settings.SAVE_API_URL
        path = url_template.format(cn_no=gr_number) if "{cn_no}" in url_template else url_template
        response = api_client.send(settings.SAVE_API_METHOD, path, payload.get("save_body", payload))
    except PermanentAPIError as exc:
        return {"success": False, "configured": True, "message": f"Save rejected by upstream: {exc}"}
    except TemporaryAPIError as exc:
        return {"success": False, "configured": True, "message": f"Save failed (temporary): {exc}"}

    if isinstance(response, dict) and response.get("status") == "success":
        return {"success": True, "configured": True, "message": "Modification saved successfully.", "response": response}

    return {
        "success": False,
        "configured": True,
        "message": "Save API responded, but did not confirm success.",
        "response": response,
    }


def verify_after_save_generic(module_key: str, gr_number: str, expected_value, expected_remark: str) -> dict:
    """
    Re-fetch the CN after a save and compare against what was expected.
    Returns {"verified": bool, "actual_value": ..., "actual_remark": ...}.
    NEVER assume a save succeeded just because the HTTP call returned 200 -
    this is the only source of truth for VERIFIED_SUCCESS vs
    VERIFICATION_FAILED.
    """
    module = get_module(module_key)
    field = module["current_code_field"] if module["kind"] == "code" else module["current_value_field"]

    try:
        fresh_cn = fetch_cn_details(gr_number)
    except (CNNotFoundError, CNLookupError) as exc:
        return {
            "verified": False,
            "actual_value": None,
            "actual_remark": None,
            "message": f"Could not re-fetch CN to verify: {exc}",
        }

    actual_value = fresh_cn.get(field)
    actual_remark = fresh_cn.get("cnRemarks")

    value_matches = (expected_value is None) or (str(actual_value) == str(expected_value))
    remark_matches = normalize_text(actual_remark) == normalize_text(expected_remark)

    return {
        "verified": bool(value_matches and remark_matches),
        "actual_value": actual_value,
        "actual_remark": actual_remark,
        "message": "Verified against upstream." if (value_matches and remark_matches) else
                   "Save call succeeded but the re-fetched CN does not match what was expected.",
    }
