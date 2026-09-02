# ==========================================
# OM Automation V2
# core/mapper.py
# ==========================================

from modules.om_automation.config import CN_HEADERS


def normalize_header(text):
    """
    Normalize Excel header for matching.

    Example:

    CN No      -> cn no
    CN_NO      -> cn no
    Manual_CN  -> manual cn
    """

    if text is None:
        return ""

    text = str(text).strip().lower()

    text = text.replace("_", " ")

    while "  " in text:
        text = text.replace("  ", " ")

    return text


def get_columns(sheet, header_list):
    """
    Generic version of get_cn_columns: returns every column
    whose normalized header matches something in header_list.
    Used by the CN, GST, and Party Code query pages, each with
    their own alias list (config.CN_HEADERS / GSTIN_HEADERS /
    PARTY_HEADERS).
    """

    columns = []

    headers = next(
        sheet.iter_rows(
            min_row=1,
            max_row=1,
            values_only=True
        )
    )

    for index, header in enumerate(headers):

        h = normalize_header(header)

        if h in header_list:

            columns.append({
                "index": index,
                "header": header
            })

    return columns


def get_cn_columns(sheet):
    """
    Returns every CN related column.

    Output Example:

    [
        {
            "index":0,
            "header":"CN"
        },
        {
            "index":3,
            "header":"Manual CN"
        }
    ]
    """

    return get_columns(sheet, CN_HEADERS)


def has_cn_column(sheet):

    return len(get_cn_columns(sheet)) > 0


def print_detected_columns(sheet):
    """
    Prints every detected CN-related column for a sheet.
    Useful for debugging header detection issues.
    """

    cols = get_cn_columns(sheet)

    if len(cols) == 0:
        print(f"[MAPPER] Sheet '{sheet.title}': no CN columns detected.")
        return cols

    print(f"[MAPPER] Sheet '{sheet.title}': {len(cols)} CN column(s) detected:")

    for col in cols:
        print(f"    - Column {col['index'] + 1}: '{col['header']}'")

    return cols
