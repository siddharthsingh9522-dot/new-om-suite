"""
Freight Mode / Transport Mode label <-> backend numeric code mappings.

Fully confirmed 29 Aug 2026 - the user manually checked every single code
against the real system, one at a time (not inferred, not guessed). This
superseded an earlier partial/incorrect mapping in this file that had
"SURFACE" = 4, which was wrong - that appears to have come from an
incorrect cross-reference between two different CNs earlier in this
project's history. Trust this table as the authoritative source; if a
transport/freight mode ever appears to behave differently, treat this
table as correct and look for a bug in the calling code first, rather
than second-guessing this table without a fresh manual re-check.
"""

# label -> numeric backend code, in the real dropdown's display order.
FREIGHT_MODE_CONFIRMED = {
    "PREPAID": 1,
    "TO PAY": 2,
    "TBB(T.P)": 3,
    "TO BILL(CNE)": 4,
    "TO BILL(CNR)": 5,
    "F.O.C": 6,
}
TRANSPORT_MODE_CONFIRMED = {
    "SURFACE": 1,
    "EXPRESS": 2,
    "TRAIN": 3,
    "AIR": 4,
    "WH": 5,
    "SHIP": 6,
    "SPEED TRUCKING": 7,
    "HAND CARRY": 8,
    "TRAIN STN DLY": 9,
    "AIR EXPRESS": 10,
    "IN CONTAINER": 11,
    "ALL": 12,
}

FREIGHT_MODE_LABELS = list(FREIGHT_MODE_CONFIRMED.keys())
TRANSPORT_MODE_LABELS = list(TRANSPORT_MODE_CONFIRMED.keys())

FREIGHT_MODE_CONFIRMED_REVERSE = {v: k for k, v in FREIGHT_MODE_CONFIRMED.items()}
TRANSPORT_MODE_CONFIRMED_REVERSE = {v: k for k, v in TRANSPORT_MODE_CONFIRMED.items()}


def freight_label_for_code(code):
    """Label for a raw cnFreightPaidMode code - None if it's outside the confirmed 1-6 range."""
    try:
        return FREIGHT_MODE_CONFIRMED_REVERSE.get(int(code))
    except (TypeError, ValueError):
        return None


def transport_label_for_code(code):
    """Label for a raw cnTptrMode code - None if it's outside the confirmed 1-12 range."""
    try:
        return TRANSPORT_MODE_CONFIRMED_REVERSE.get(int(code))
    except (TypeError, ValueError):
        return None


def freight_code_for_label(label):
    """Numeric code for a Freight Mode label."""
    return FREIGHT_MODE_CONFIRMED.get((label or "").strip())


def transport_code_for_label(label):
    """Numeric code for a Transport Mode label."""
    return TRANSPORT_MODE_CONFIRMED.get((label or "").strip())
