"""
Module registry for the generic modifier engine.

The ORIGINAL Billing Party module (routes/single_cn.py, routes/bulk.py,
services/modification_service.py, models/batch.py, models/batch_item.py)
is completely untouched and keeps running exactly as it always has - it is
NOT part of this registry and does not go through the generic engine.

This registry describes the FOUR NEW modules (Consignor, Consignee,
Freight Mode, Transport Mode). Each one is plain configuration - no new
Python logic is needed to add a module, only an entry here - because they
all share services/generic_modifier_service.py, models/module_batch.py,
models/module_batch_item.py, and routes/modules.py.

Two module "kinds" are supported:

- "code": the value being changed is a customer/party code that must be
  validated via the existing GET /manual-cn/details/{code} API (exactly
  like Billing Party). Consignor and Consignee are this kind.
- "dropdown": the value being changed is a fixed-vocabulary mode/status
  code with no external validation call (Freight Mode, Transport Mode).

The Freight/Transport Mode option lists below are the FULLY CONFIRMED
label<->code tables (see config/mode_mappings.py) - the user manually
checked every single code against the real system on 29 Aug 2026. An
earlier version of this mapping was partial and had one wrong entry
("SURFACE" was incorrectly believed to be code 4; it is actually 1) -
that has been corrected. Override via the FREIGHT_MODE_OPTIONS /
TRANSPORT_MODE_OPTIONS env vars only if a genuinely new code is
discovered later - don't hand-edit around this confirmed table without
a fresh manual re-check backing the change.
"""
import json
import os


def _load_options_from_env(env_var: str, fallback: list):
    """
    Each option is {"value": <raw code sent to/from the API>, "label": <what
    the operator sees>}. Configure via an env var containing a JSON array,
    e.g. FREIGHT_MODE_OPTIONS='[{"value":"5","label":"TO BILL(CNR)"}]'.
    """
    raw = os.getenv(env_var)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return fallback


# Fully confirmed 29 Aug 2026 - the user manually checked every code
# against the real system. Sourced from config/mode_mappings.py (the
# single source of truth for these tables) rather than duplicated here,
# so there is only one place to update if a mapping is ever revised.
from config.mode_mappings import FREIGHT_MODE_CONFIRMED, TRANSPORT_MODE_CONFIRMED

_FREIGHT_MODE_FALLBACK = [{"value": str(code), "label": label} for label, code in FREIGHT_MODE_CONFIRMED.items()]
_TRANSPORT_MODE_FALLBACK = [{"value": str(code), "label": label} for label, code in TRANSPORT_MODE_CONFIRMED.items()]

MODULE_CONSIGNOR = "consignor"
MODULE_CONSIGNEE = "consignee"
MODULE_FREIGHT_MODE = "freight_mode"
MODULE_TRANSPORT_MODE = "transport_mode"

MODULES = {
    MODULE_CONSIGNOR: {
        "key": MODULE_CONSIGNOR,
        "kind": "code",
        "display_name": "Consignor Details Modification",
        "short_name": "Consignor",
        "icon": "bi-person-badge",
        "current_code_field": "cnConsignorCode",
        "current_name_field": "cnConsignorName",
        "write_code_field": "cnConsignorCode",
        "write_name_field": "cnConsignorName",
        "value_label": "Consignor Code",
    },
    MODULE_CONSIGNEE: {
        "key": MODULE_CONSIGNEE,
        "kind": "code",
        "display_name": "Consignee Details Modification",
        "short_name": "Consignee",
        "icon": "bi-person-lines-fill",
        "current_code_field": "cnConsigneeCode",
        "current_name_field": "cnConsigneeName",
        "write_code_field": "cnConsigneeCode",
        "write_name_field": "cnConsigneeName",
        "value_label": "Consignee Code",
    },
    MODULE_FREIGHT_MODE: {
        "key": MODULE_FREIGHT_MODE,
        "kind": "dropdown",
        "display_name": "Freight Mode Modification",
        "short_name": "Freight Mode",
        "icon": "bi-truck-flatbed",
        "current_value_field": "cnFreightPaidMode",
        "write_value_field": "cnFreightPaidMode",
        "value_label": "Freight Mode",
        "options": _load_options_from_env("FREIGHT_MODE_OPTIONS", _FREIGHT_MODE_FALLBACK),
    },
    MODULE_TRANSPORT_MODE: {
        "key": MODULE_TRANSPORT_MODE,
        "kind": "dropdown",
        "display_name": "Transport Mode Modification",
        "short_name": "Transport Mode",
        "icon": "bi-signpost-split",
        "current_value_field": "cnTptrMode",
        "write_value_field": "cnTptrMode",
        "value_label": "Transport Mode",
        "options": _load_options_from_env("TRANSPORT_MODE_OPTIONS", _TRANSPORT_MODE_FALLBACK),
    },
}


def get_module(module_key: str):
    module = MODULES.get(module_key)
    if not module:
        raise KeyError(f"Unknown module: {module_key}")
    return module


def all_modules():
    return list(MODULES.values())
