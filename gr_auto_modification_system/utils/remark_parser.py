"""
Remark parsing and merge logic.

Responsible for:
 - Extracting a Party Code from a free-text remark (robust, case-insensitive)
 - Merging a new remark with an existing remark per business rules
 - Detecting whether a remark has already been applied (duplicate protection)
"""
import re

# Matches: CODE 838219 / C0DE 838219 / code 838219 / CODE:838219 / C0DE:838219 /
#          CODE-838219 / C0DE-838219 / COD3 838219 / billing 838219 / billing:838219 ...
#
# \b at the start prevents matching inside an unrelated word (e.g. the
# "code" in "barcode" or "zipcode", or "billing" inside "ambattur_billing1",
# should NOT match - "_" counts as a word character so no boundary exists
# there). The keyword itself tolerates the common 0/O and 3/E OCR-style
# substitutions seen in these remarks. "billing" is recognized as an
# equally-valid trigger word alongside "CODE" - this is the operators'
# actual day-to-day remark convention ("billing 935091 @name dt...") and
# was the real-world cause of a party-code-not-detected regression when
# only the CODE/C0DE/COD3 family was recognized. Digits are constrained to
# 4-10 so we don't accidentally grab a 2-3 digit date fragment or similar
# stray number sitting next to the word.
_PARTY_CODE_PATTERN = re.compile(
    r"""
    \b (?:c[o0]d[e3]|billing)   # CODE / C0DE / COD3 / C0D3 / billing (case-insensitive via re.I)
    \s*[:\-]?\s*                 # optional separator: colon, hyphen, or just whitespace
    (\d{4,10}) \b                # the actual numeric party code
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_party_code(remark: str):
    """
    Attempt to extract a Party Code from a free-text remark.

    Recognizes the "CODE <number>" family (CODE, C0DE, CODE:, CODE-, code,
    etc.) AND "billing <number>" (the operators' other real day-to-day
    convention). There is deliberately no blind "any bare number"
    fallback beyond these specific trigger words, since that risks
    misidentifying a date, a CN number, or another unrelated figure
    elsewhere in the remark as the Party Code - if a new convention shows
    up in practice, add its keyword here rather than falling back to a
    blind number match.

    Returns:
        (party_code: str | None, method: str)
        method is one of: "matched_code_keyword", "not_found"
    """
    if not remark or not remark.strip():
        return None, "not_found"

    match = _PARTY_CODE_PATTERN.search(remark)
    if match:
        return match.group(1), "matched_code_keyword"

    return None, "not_found"


def normalize_text(text: str) -> str:
    """Collapse whitespace and trim, for comparison purposes."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def already_applied(existing_remark: str, new_remark: str) -> bool:
    """
    True if the (normalized) new remark is already present at the very
    beginning of the existing remark - i.e. it has already been applied.
    """
    existing_norm = normalize_text(existing_remark)
    new_norm = normalize_text(new_remark)
    if not new_norm:
        return False
    return existing_norm.startswith(new_norm)


def build_final_remark(existing_remark: str, new_remark: str):
    """
    Build the FINAL_REMARK per business rules and report the action taken.

    Returns:
        (final_remark: str, action: str)
        action is one of: "READY", "ALREADY_APPLIED"
    """
    existing_norm = normalize_text(existing_remark)
    new_norm = normalize_text(new_remark)

    if already_applied(existing_norm, new_norm):
        # Duplicate protection - do not re-prepend.
        return existing_norm, "ALREADY_APPLIED"

    if not existing_norm:
        return new_norm, "READY"

    final_remark = f"{new_norm} {existing_norm}".strip()
    return final_remark, "READY"
