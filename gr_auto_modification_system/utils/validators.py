"""
Input validation helpers used across single-CN and bulk flows.
"""
import re

_GR_PATTERN = re.compile(r"^\d{5,20}$")
_MAX_REMARK_LENGTH = 1000

# Candidate column header names that likely refer to the GR/CN/Docket/LR number.
GR_COLUMN_CANDIDATES = [
    "gr", "gr no", "gr number", "grno",
    "cn", "cn no", "cn number", "cnno",
    "docket", "docket no", "docket number",
    "lr", "lr no", "lr number", "lrno",
]


def is_valid_gr_number(value) -> bool:
    """A GR/CN/Docket/LR number must be a numeric string of reasonable length."""
    if value is None:
        return False
    value = str(value).strip()
    return bool(_GR_PATTERN.match(value))


def is_valid_party_code(value) -> bool:
    if value is None:
        return False
    value = str(value).strip()
    return value.isdigit() and 1 <= len(value) <= 12


def validate_remark_length(remark: str):
    if remark is None:
        return False, "Remark cannot be empty."
    remark = remark.strip()
    if not remark:
        return False, "Remark cannot be empty."
    if len(remark) > _MAX_REMARK_LENGTH:
        return False, f"Remark exceeds maximum length of {_MAX_REMARK_LENGTH} characters."
    return True, None


def guess_gr_column(columns):
    """
    Given a list of Excel column header strings, guess which one holds the
    GR/CN/Docket/LR number. Returns the matched column name, or None if no
    confident match is found (caller should then prompt the user).
    """
    normalized = {str(c).strip().lower(): c for c in columns}
    for candidate in GR_COLUMN_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]

    # Loose contains-match fallback (still fairly confident)
    for lower_name, original in normalized.items():
        for keyword in ("gr", "cn", "docket", "lr"):
            if keyword in lower_name:
                return original
    return None
