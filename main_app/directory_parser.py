"""
Directory aur report/TBB sheet ko parse karne ke liye helper functions.

Ye Om Group ki multi-sheet Employee/Branch Directory (.xls/.xlsx)
aur daily "report" / TBB Party sheet dono ko parse karta hai.

FIXES:
- TBB report ka header row automatically detect hota hai.
- B.CODE / B. CODE / B CODE / BRANCH CODE / BCODE supported.
- Extra title/date rows supported.
- Column names normalize hote hain.
- Branch, CN, Party Code, Party Name, CN Date correctly detect hote hain.
- Better error message with detected columns.
"""

import re
import pandas as pd
from collections import defaultdict


# ============================================================
# DIRECTORY CONFIGURATION
# ============================================================

DIRECTORY_SHEETS_DEFAULT = [
    'OLSC BRANCHES',
    'OTL BRANCHES',
    'PUNE',
    'CORP.OFFICE',
    'OMX INFO',
    'TRANSAFE',
    'RAPIDSHYP',
    'ICD BAWAL'
]


INCHARGE_KEYWORDS = [
    'BRANCH MANAGER',
    'BRANCH IN-CHARGE',
    'BRANCH INCHARGE',
    'BRANCH  IN-CHARGE',
    'SR.BRANCH MANAGER',
    'SR BRANCH MANAGER',
    'BRANCH  MANAGER',
    'SR. BRANCH MANAGER'
]


# ============================================================
# GENERAL HELPERS
# ============================================================

def _clean_email_list(raw):
    """
    Raw email field se valid email IDs extract karta hai.
    """

    if pd.isna(raw):
        return []

    raw = str(raw).replace('\xa0', ' ')

    parts = re.split(r'[\/,;]', raw)

    out = []

    for p in parts:

        p = p.strip()

        if (
            p
            and '@' in p
            and '.' in p.split('@')[-1]
        ):
            out.append(p.lower())

    return out


def _normalize_text(value):
    """
    General text normalization.
    """

    if pd.isna(value):
        return ''

    value = str(value)

    value = value.replace('\xa0', ' ')
    value = value.replace('\n', ' ')
    value = value.replace('\r', ' ')

    value = re.sub(r'\s+', ' ', value)

    return value.strip()


def _normalize_header(value):
    """
    Excel header ko standard format mein convert karta hai.

    Example:

    B.CODE       -> B.CODE
    B. CODE      -> B. CODE
    Branch Code  -> BRANCH CODE
    Party Code   -> PARTY CODE
    """

    value = _normalize_text(value)

    return value.upper()


def _safe_branch_code(value):
    """
    Branch code ko consistent string mein convert karta hai.

    301.0 -> 301
    1301  -> 1301
    "301" -> 301
    """

    if pd.isna(value):
        return ''

    try:
        number = float(value)

        if number.is_integer():
            return str(int(number))

    except (ValueError, TypeError):
        pass

    return str(value).strip()


# ============================================================
# DIRECTORY HEADER DETECTION
# ============================================================

def _find_header_row(df, max_scan=10):
    """
    Directory Excel sheet mein Branch Code wala header row dhoondhta hai.
    """

    for i in range(min(max_scan, len(df))):

        row_vals = [
            _normalize_header(x)
            for x in df.iloc[i].tolist()
        ]

        joined = ' '.join(row_vals)

        if 'BRANCH CODE' in joined:
            return i

    # Existing behaviour maintain
    return 1


def _col_index(header_row, keywords, exclude=None):
    """
    Directory header row mein matching column index return karta hai.
    """

    exclude = exclude or []

    normalized_header = [
        _normalize_header(x)
        for x in header_row
    ]

    for kw in keywords:

        kw = _normalize_header(kw)

        for idx, val in enumerate(normalized_header):

            if idx in exclude:
                continue

            if not val:
                continue

            if kw in val:
                return idx

    return None


# ============================================================
# DIRECTORY PARSER
# ============================================================

def parse_directory(filepath, sheets=None):
    """
    Directory file (.xls/.xlsx) padhta hai aur:

        {
            branch_code: [
                {
                    name,
                    designation,
                    emails,
                    branch_name
                }
            ]
        }

    return karta hai.

    Sirf configured branch/employee sheets scan hoti hain.
    """

    sheets = sheets or DIRECTORY_SHEETS_DEFAULT

    xls = pd.ExcelFile(filepath)

    available = [
        s for s in sheets
        if s in xls.sheet_names
    ]

    emp_by_branch = defaultdict(list)

    for sheet in available:

        df = xls.parse(
            sheet,
            header=None
        )

        hdr_i = _find_header_row(df)

        header_row = df.iloc[hdr_i]

        c_name = _col_index(
            header_row,
            [
                'BRANCH NAME',
                'STATE/ BRANCH',
                'STATE/BRANCH',
                'STATE / BRANCH'
            ]
        )

        c_code = _col_index(
            header_row,
            [
                'BRANCH CODE'
            ]
        )

        c_person = _col_index(
            header_row,
            [
                'OFFICIAL',
                'EMPLOYEES NAME',
                'EMPLOYEE NAME'
            ],
            exclude=[
                c_name
            ] if c_name is not None else []
        )

        c_desig = _col_index(
            header_row,
            [
                'DESIGNATION'
            ]
        )

        c_email = _col_index(
            header_row,
            [
                'E-MAIL',
                'E - MAIL',
                'EMAIL'
            ]
        )

        if c_code is None or c_email is None:
            continue

        cur_code = None
        cur_name = None

        for i in range(
            hdr_i + 1,
            len(df)
        ):

            row = df.iloc[i]

            if row.isna().all():
                continue

            c0 = (
                row[c_name]
                if c_name is not None
                else None
            )

            c1 = row[c_code]

            cP = (
                row[c_person]
                if c_person is not None
                else None
            )

            cD = (
                row[c_desig]
                if c_desig is not None
                else None
            )

            cM = row[c_email]

            # ------------------------------------------------
            # New branch code found
            # ------------------------------------------------

            if pd.notna(c1):

                cur_code = _safe_branch_code(c1)

                if pd.notna(c0):

                    cur_name = str(c0).strip()

                emails = _clean_email_list(cM)

                if pd.notna(cP) or emails:

                    emp_by_branch[cur_code].append({
                        'branch_name': cur_name,
                        'name': cP,
                        'designation': cD,
                        'emails': emails
                    })

            # ------------------------------------------------
            # Ignore branch separator / blank rows
            # ------------------------------------------------

            elif (
                pd.notna(c0)
                and pd.isna(cP)
                and not _clean_email_list(cM)
            ):

                continue

            # ------------------------------------------------
            # Same branch continuation row
            # ------------------------------------------------

            else:

                if cur_code is not None:

                    emails = _clean_email_list(cM)

                    if pd.notna(cP) or emails:

                        emp_by_branch[cur_code].append({
                            'branch_name': cur_name,
                            'name': cP,
                            'designation': cD,
                            'emails': emails
                        })

    return dict(emp_by_branch)


# ============================================================
# SINGLE BRANCH EMAIL
# ============================================================

def pick_branch_email(directory, branch_code):
    """
    Diye gaye branch code ke liye sabse suitable email choose karta hai.

    Priority:

    1. Branch Manager / Incharge
    2. Any valid email
    """

    entries = directory.get(
        str(branch_code).strip(),
        []
    )

    # --------------------------------------------------------
    # First priority: Incharge / Manager
    # --------------------------------------------------------

    for e in entries:

        des = e.get('designation') or ''

        des = (
            ''
            if str(des) in ('nan', 'None')
            else str(des).upper()
        )

        if (
            e.get('emails')
            and any(
                k in des
                for k in INCHARGE_KEYWORDS
            )
        ):

            return (
                e['emails'][0],
                e.get('name'),
                e.get('designation')
            )

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    for e in entries:

        if e.get('emails'):

            return (
                e['emails'][0],
                e.get('name'),
                e.get('designation')
            )

    return None, None, None


# ============================================================
# ROLE CONTACTS
# ============================================================

ROLE_KEYWORDS = {

    'incharge': INCHARGE_KEYWORDS,

    'billing': [
        'BILLING',
        'CASHIER',
        'ACCOUNTS',
        'ACCOUNTANT'
    ],

    'delivery': [
        'DELIVERY INCHARGE',
        'DELIVERY IN-CHARGE',
        'DELIVERY  INCHARGE',
        'DELIVERY BOY',
        'DELIVERY'
    ],

    'dbp': [
        'DBP'
    ],
}


def pick_branch_role_contacts(directory, branch_code):
    """
    Branch ke:

    - Incharge
    - Billing
    - Delivery
    - DBP

    contacts find karta hai.

    Duplicate emails sirf ek baar aate hain.

    Returns:
        (emails, display_names)
    """

    entries = directory.get(
        str(branch_code).strip(),
        []
    )

    found_emails = []
    found_names = []

    seen = set()

    for role, keywords in ROLE_KEYWORDS.items():

        for e in entries:

            des = e.get('designation') or ''

            des = (
                ''
                if str(des) in ('nan', 'None')
                else str(des).upper()
            )

            emails = e.get('emails') or []

            if (
                emails
                and any(
                    k in des
                    for k in keywords
                )
            ):

                email = emails[0]

                if email not in seen:

                    seen.add(email)

                    found_emails.append(email)

                    found_names.append(
                        f"{e.get('name', '')} "
                        f"({e.get('designation', '')})"
                    )

                # Is role ka first match enough
                break

    return found_emails, found_names


# ============================================================
# TBB / REPORT COLUMN CONFIGURATION
# ============================================================

REPORT_COL_KEYWORDS = {

    # --------------------------------------------------------
    # Branch Code
    # --------------------------------------------------------

    'branch_code': [
        'B. CODE',
        'B.CODE',
        'B CODE',
        'BRANCH CODE',
        'BRANCHCODE',
        'BRANCH CD',
        'BCODE'
    ],

    # --------------------------------------------------------
    # Branch Name
    # --------------------------------------------------------

    'branch_name': [
        'BRANCH NAME',
        'BRANCHNAME',
        'STATE/ BRANCH',
        'STATE/BRANCH',
        'STATE / BRANCH',
        'BRANCH'
    ],

    # --------------------------------------------------------
    # Region
    # --------------------------------------------------------

    'region': [
        'REGION'
    ],

    # --------------------------------------------------------
    # CN / GR
    # --------------------------------------------------------

    'cn': [
        'CN',
        'GR NO',
        'GR NUMBER',
        'GRNO'
    ],

    # --------------------------------------------------------
    # Party
    # --------------------------------------------------------

    'party_code': [
        'PARTY CODE'
    ],

    'party_name': [
        'PARTY NAME'
    ],

    # --------------------------------------------------------
    # CN Date
    # --------------------------------------------------------

    'cn_date': [
        'CN DATE',
        'GR DATE'
    ],
}


# ============================================================
# REPORT HEADER NORMALIZATION
# ============================================================

def _normalize_report_header(value):
    """
    Report header ko standard form mein convert karta hai.
    """

    if pd.isna(value):
        return ''

    value = str(value)

    value = value.replace(
        '\xa0',
        ' '
    )

    value = value.replace(
        '\n',
        ' '
    )

    value = value.replace(
        '\r',
        ' '
    )

    value = re.sub(
        r'\s+',
        ' ',
        value
    )

    return value.strip().upper()


# ============================================================
# REPORT HEADER DETECTION
# ============================================================

def _find_report_header_row(df, max_scan=20):
    """
    Report Excel ki first 20 rows mein actual header row detect karta hai.

    Supported branch-code headers:

        B.CODE
        B. CODE
        B CODE
        BRANCH CODE
        BRANCHCODE
        BRANCH CD
        BCODE
    """

    branch_code_headers = {
        'B.CODE',
        'B. CODE',
        'B CODE',
        'BRANCH CODE',
        'BRANCHCODE',
        'BRANCH CD',
        'BCODE'
    }

    for i in range(
        min(max_scan, len(df))
    ):

        row_values = [
            _normalize_report_header(x)
            for x in df.iloc[i].tolist()
        ]

        for value in row_values:

            if value in branch_code_headers:
                return i

    return None


# ============================================================
# REPORT COLUMN MATCHING
# ============================================================

def _match_report_column(columns, keywords):
    """
    Report columns ko intelligently match karta hai.

    Priority:

    1. Exact match
    2. Normalized exact match
    3. Contains match
    """

    # --------------------------------------------------------
    # Prepare normalized columns
    # --------------------------------------------------------

    normalized_columns = {}

    for c in columns:

        normalized = _normalize_report_header(c)

        normalized_columns[c] = normalized

    # --------------------------------------------------------
    # 1. Exact match
    # --------------------------------------------------------

    for kw in keywords:

        kw_norm = _normalize_report_header(kw)

        for c, normalized in normalized_columns.items():

            if normalized == kw_norm:
                return c

    # --------------------------------------------------------
    # 2. Contains match
    # --------------------------------------------------------

    for kw in keywords:

        kw_norm = _normalize_report_header(kw)

        for c, normalized in normalized_columns.items():

            if (
                kw_norm
                and kw_norm in normalized
            ):
                return c

    return None


# ============================================================
# SAFE CELL VALUE
# ============================================================

def _safe_cell_value(row, column):
    """
    DataFrame row se safe string value return karta hai.
    """

    if column is None:
        return ''

    try:
        value = row[column]
    except (KeyError, IndexError):
        return ''

    if pd.isna(value):
        return ''

    return str(value).strip()


# ============================================================
# TBB / REPORT PARSER
# ============================================================

def parse_report(filepath, sheet_name=0):
    """
    Daily Report / TBB sheet parse karta hai.

    Output:

    {
        branch_code: {
            'branch_code': '301',
            'branch_name_sheet': 'AHMEDABAD',
            'region': '',
            'grs': [
                {
                    'cn': '5704261006476',
                    'party_code': '685297',
                    'party_name': 'STANMARK HEALTHCARE PVT LTD',
                    'cn_date': '26-09-2026'
                }
            ]
        }
    }

    IMPORTANT:
    Excel mein agar report title/date ki extra rows hain,
    to actual header automatically detect hota hai.
    """

    # ========================================================
    # STEP 1
    # Raw Excel read
    #
    # header=None is VERY IMPORTANT.
    # Isse pandas first row ko automatically header nahi banayega.
    # ========================================================

    try:

        raw_df = pd.read_excel(
            filepath,
            sheet_name=sheet_name,
            header=None
        )

    except Exception as exc:

        raise ValueError(
            f"Report Excel read nahi ho paayi: {exc}"
        ) from exc

    # ========================================================
    # STEP 2
    # Detect actual header row
    # ========================================================

    header_row = _find_report_header_row(
        raw_df,
        max_scan=20
    )

    if header_row is None:

        preview = raw_df.head(10).to_string(
            index=False
        )

        raise ValueError(
            "Report sheet mein "
            "'B.CODE' / 'Branch Code' "
            "wala header nahi mila.\n\n"
            "Excel ki first 10 rows:\n\n"
            f"{preview}"
        )

    # ========================================================
    # STEP 3
    # Excel ko actual header row ke saath read karo
    # ========================================================

    df = pd.read_excel(
        filepath,
        sheet_name=sheet_name,
        header=header_row
    )

    # ========================================================
    # STEP 4
    # Clean column names
    # ========================================================

    df.columns = [
        _normalize_report_header(col)
        for col in df.columns
    ]

    cols = df.columns.tolist()

    # ========================================================
    # STEP 5
    # Find required / optional columns
    # ========================================================

    col_map = {}

    for key, keywords in REPORT_COL_KEYWORDS.items():

        col_map[key] = _match_report_column(
            cols,
            keywords
        )

    # ========================================================
    # STEP 6
    # Branch Code mandatory hai
    # ========================================================

    if col_map['branch_code'] is None:

        raise ValueError(
            "Report sheet mein "
            "'B.CODE' / 'Branch Code' "
            "column nahi mila.\n\n"
            f"Detected columns:\n{cols}"
        )

    # ========================================================
    # STEP 7
    # Parse branches
    # ========================================================

    branches = {}

    for _, row in df.iterrows():

        # ----------------------------------------------------
        # Branch code
        # ----------------------------------------------------

        bc_raw = row[
            col_map['branch_code']
        ]

        if pd.isna(bc_raw):
            continue

        bc = _safe_branch_code(
            bc_raw
        )

        if not bc:
            continue

        # ----------------------------------------------------
        # Branch name
        # ----------------------------------------------------

        branch_name = ''

        if col_map['branch_name']:

            value = row[
                col_map['branch_name']
            ]

            if not pd.isna(value):

                branch_name = str(
                    value
                ).strip()

        # ----------------------------------------------------
        # Region
        # ----------------------------------------------------

        region = ''

        if col_map['region']:

            value = row[
                col_map['region']
            ]

            if not pd.isna(value):

                region = str(
                    value
                ).strip()

        # ----------------------------------------------------
        # Create branch
        # ----------------------------------------------------

        if bc not in branches:

            branches[bc] = {

                'branch_code': bc,

                'branch_name_sheet':
                    branch_name,

                'region':
                    region,

                'grs': [],
            }

        # ----------------------------------------------------
        # CN
        # ----------------------------------------------------

        cn = _safe_cell_value(
            row,
            col_map['cn']
        )

        # ----------------------------------------------------
        # Party Code
        # ----------------------------------------------------

        party_code = _safe_cell_value(
            row,
            col_map['party_code']
        )

        # ----------------------------------------------------
        # Party Name
        # ----------------------------------------------------

        party_name = ''

        if col_map['party_name']:

            value = row[
                col_map['party_name']
            ]

            if not pd.isna(value):

                party_name = value

        # ----------------------------------------------------
        # CN Date
        # ----------------------------------------------------

        cn_date = _safe_cell_value(
            row,
            col_map['cn_date']
        )

        # ----------------------------------------------------
        # Add GR/CN
        # ----------------------------------------------------

        branches[bc]['grs'].append({

            'cn': cn,

            'party_code':
                party_code,

            'party_name':
                party_name,

            'cn_date':
                cn_date,
        })

    return branches


# ============================================================
# BUILD BRANCHES + EMAIL
# ============================================================

def build_branches_with_email(
    report_branches,
    directory
):
    """
    Report se bane branches mein directory contacts add karta hai.

    Priority:

    Branch Incharge
    Billing
    Delivery
    DBP

    Agar role contacts nahi milte,
    to normal pick_branch_email fallback use hota hai.
    """

    for bc, b in report_branches.items():

        # ----------------------------------------------------
        # Role-based contacts
        # ----------------------------------------------------

        role_emails, role_names = (
            pick_branch_role_contacts(
                directory,
                bc
            )
        )

        if role_emails:

            b['email'] = ", ".join(
                role_emails
            )

            b['contact_name'] = "; ".join(
                role_names
            )

            b['designation'] = (
                f"{len(role_emails)} role(s): "
                "Incharge/Billing/Delivery/DBP"
            )

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        else:

            email, name, desig = (
                pick_branch_email(
                    directory,
                    bc
                )
            )

            b['email'] = email

            b['contact_name'] = name

            b['designation'] = desig

    return report_branches
