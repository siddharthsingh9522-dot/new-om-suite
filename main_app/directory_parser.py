"""
Directory aur report/TBB sheet ko parse karne ke liye helper functions.
Ye Om Group ki multi-sheet Employee/Branch Directory (.xls/.xlsx) aur
har roz ki "report" sheet (jaise TBB Party sheet) dono ko samajhta hai.
"""

import re
import pandas as pd
from collections import defaultdict

# Directory sheets jinko hum scan karte hain (PDA sheet jaan bujh kar skip hai,
# kyunki wo alag entity hai, branch nahi)
DIRECTORY_SHEETS_DEFAULT = [
    'OLSC BRANCHES', 'OTL BRANCHES', 'PUNE', 'CORP.OFFICE', 'OMX INFO',
    'TRANSAFE', 'RAPIDSHYP', 'ICD BAWAL'
]

INCHARGE_KEYWORDS = [
    'BRANCH MANAGER', 'BRANCH IN-CHARGE', 'BRANCH INCHARGE', 'BRANCH  IN-CHARGE',
    'SR.BRANCH MANAGER', 'SR BRANCH MANAGER', 'BRANCH  MANAGER', 'SR. BRANCH MANAGER'
]


def _clean_email_list(raw):
    if pd.isna(raw):
        return []
    raw = str(raw).replace('\xa0', ' ')
    parts = re.split(r'[\/,;]', raw)
    out = []
    for p in parts:
        p = p.strip()
        if p and '@' in p and '.' in p.split('@')[-1]:
            out.append(p.lower())
    return out


def _find_header_row(df, max_scan=6):
    for i in range(min(max_scan, len(df))):
        row_vals = [str(x) for x in df.iloc[i].tolist()]
        joined = ' '.join(row_vals).upper()
        if 'BRANCH CODE' in joined:
            return i
    return 1


def _col_index(header_row, keywords, exclude=None):
    exclude = exclude or []
    for kw in keywords:
        for idx, val in enumerate(header_row):
            if idx in exclude or pd.isna(val):
                continue
            v = str(val).upper().replace('\n', ' ').replace('.', ' ')
            v = re.sub(r'\s+', ' ', v).strip()
            if kw in v:
                return idx
    return None


def parse_directory(filepath, sheets=None):
    """
    Directory file (.xls/.xlsx) padhta hai aur {branch_code: [ {name, designation, emails}, ... ]}
    return karta hai. Sirf branch/employee wali sheets scan hoti hain.
    """
    sheets = sheets or DIRECTORY_SHEETS_DEFAULT
    xls = pd.ExcelFile(filepath)
    available = [s for s in sheets if s in xls.sheet_names]

    emp_by_branch = defaultdict(list)

    for sheet in available:
        df = xls.parse(sheet, header=None)
        hdr_i = _find_header_row(df)
        header_row = df.iloc[hdr_i]

        c_name = _col_index(header_row, ['BRANCH NAME', 'STATE/ BRANCH', 'STATE/BRANCH', 'STATE / BRANCH'])
        c_code = _col_index(header_row, ['BRANCH CODE'])
        c_person = _col_index(header_row, ['OFFICIAL', 'EMPLOYEES NAME', 'EMPLOYEE NAME'],
                               exclude=[c_name] if c_name is not None else [])
        c_desig = _col_index(header_row, ['DESIGNATION'])
        c_email = _col_index(header_row, ['E-MAIL', 'E - MAIL', 'EMAIL'])

        if c_code is None or c_email is None:
            continue

        cur_code = None
        cur_name = None
        for i in range(hdr_i + 1, len(df)):
            row = df.iloc[i]
            if row.isna().all():
                continue
            c0 = row[c_name] if c_name is not None else None
            c1 = row[c_code]
            cP = row[c_person] if c_person is not None else None
            cD = row[c_desig] if c_desig is not None else None
            cM = row[c_email]

            if pd.notna(c1):
                try:
                    cur_code = str(int(float(c1)))
                except (ValueError, TypeError):
                    cur_code = str(c1).strip()
                cur_name = str(c0).strip() if pd.notna(c0) else cur_name
                emails = _clean_email_list(cM)
                if pd.notna(cP) or emails:
                    emp_by_branch[cur_code].append({
                        'branch_name': cur_name, 'name': cP, 'designation': cD, 'emails': emails
                    })
            elif pd.notna(c0) and pd.isna(cP) and not _clean_email_list(cM):
                continue
            else:
                if cur_code is not None:
                    emails = _clean_email_list(cM)
                    if pd.notna(cP) or emails:
                        emp_by_branch[cur_code].append({
                            'branch_name': cur_name, 'name': cP, 'designation': cD, 'emails': emails
                        })
    return dict(emp_by_branch)


def pick_branch_email(directory, branch_code):
    """Diye gaye branch code ke liye sabse sahi email chunta hai (pehle Manager/Incharge, warna koi bhi valid email)."""
    entries = directory.get(str(branch_code).strip(), [])
    for e in entries:
        des = e.get('designation') or ''
        des = '' if str(des) in ('nan', 'None') else str(des).upper()
        if e.get('emails') and any(k in des for k in INCHARGE_KEYWORDS):
            return e['emails'][0], e.get('name'), e.get('designation')
    for e in entries:
        if e.get('emails'):
            return e['emails'][0], e.get('name'), e.get('designation')
    return None, None, None


# TBB Party mail ke liye — branch ki saari relevant roles (Incharge + Billing + Delivery + DBP)
# ek saath TO mein daalne ke liye. Har role ka pehla match liya jata hai.
ROLE_KEYWORDS = {
    'incharge': INCHARGE_KEYWORDS,
    'billing': ['BILLING', 'CASHIER', 'ACCOUNTS', 'ACCOUNTANT'],
    'delivery': ['DELIVERY INCHARGE', 'DELIVERY IN-CHARGE', 'DELIVERY  INCHARGE', 'DELIVERY BOY', 'DELIVERY'],
    'dbp': ['DBP'],
}


def pick_branch_role_contacts(directory, branch_code):
    """Branch ke Incharge, Billing, Delivery aur DBP — har role ka pehla match dhoondh kar
    ek combined list return karta hai. Duplicate emails (jaise ek hi banda do role handle kare)
    sirf ek baar aate hain. Returns: (emails: list[str], display_names: list[str])"""
    entries = directory.get(str(branch_code).strip(), [])
    found_emails = []
    found_names = []
    seen = set()
    for role, keywords in ROLE_KEYWORDS.items():
        for e in entries:
            des = e.get('designation') or ''
            des = '' if str(des) in ('nan', 'None') else str(des).upper()
            emails = e.get('emails') or []
            if emails and any(k in des for k in keywords):
                email = emails[0]
                if email not in seen:
                    seen.add(email)
                    found_emails.append(email)
                    found_names.append(f"{e.get('name','')} ({e.get('designation','')})")
                break  # is role ke liye pehla match mil gaya, agle role par jao
    return found_emails, found_names


# Report/TBB sheet mein column naam alag ho sakte hain, isliye keyword-based match
REPORT_COL_KEYWORDS = {
    'branch_code': ['B. CODE', 'B.CODE', 'BRANCH CODE', 'BCODE'],
    'branch_name': ['BRANCH'],
    'region': ['REGION'],
    'cn': ['CN', 'GR NO', 'GR NUMBER', 'GRNO'],
    'party_code': ['PARTY CODE'],
    'party_name': ['PARTY NAME'],
    'cn_date': ['CN DATE', 'GR DATE'],
}


def _match_report_column(columns, keywords):
    upper_cols = {c: str(c).upper().strip() for c in columns}
    # exact match first
    for kw in keywords:
        for c, u in upper_cols.items():
            if u == kw:
                return c
    # contains match
    for kw in keywords:
        for c, u in upper_cols.items():
            if kw in u:
                return c
    return None


def parse_report(filepath, sheet_name=0):
    """
    Report/TBB sheet padhta hai aur branch_code -> {branch_name, region, grs:[...]} banata hai.
    Column naam thode alag ho to bhi (keyword match se) chal jayega.
    """
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    cols = df.columns.tolist()

    col_map = {}
    for key, kws in REPORT_COL_KEYWORDS.items():
        col_map[key] = _match_report_column(cols, kws)

    if col_map['branch_code'] is None:
        raise ValueError("Report sheet mein 'Branch Code' jaisa column nahi mila. Column headers check karein.")

    branches = {}
    for _, row in df.iterrows():
        bc_raw = row[col_map['branch_code']]
        if pd.isna(bc_raw):
            continue
        try:
            bc = str(int(float(bc_raw)))
        except (ValueError, TypeError):
            bc = str(bc_raw).strip()

        if bc not in branches:
            branches[bc] = {
                'branch_code': bc,
                'branch_name_sheet': row[col_map['branch_name']] if col_map['branch_name'] else '',
                'region': row[col_map['region']] if col_map['region'] else '',
                'grs': [],
            }
        branches[bc]['grs'].append({
            'cn': str(row[col_map['cn']]) if col_map['cn'] else '',
            'party_code': str(row[col_map['party_code']]) if col_map['party_code'] else '',
            'party_name': row[col_map['party_name']] if col_map['party_name'] else '',
            'cn_date': str(row[col_map['cn_date']]) if col_map['cn_date'] else '',
        })
    return branches


def build_branches_with_email(report_branches, directory):
    """Report se bane branches mein directory se email/contact jod deta hai.
    TBB Party mail ke liye — Branch Incharge + Billing + Delivery + DBP, sabko TO mein
    ek saath daalta hai (agar koi role na mile to fallback single-email logic use hoti hai)."""
    for bc, b in report_branches.items():
        role_emails, role_names = pick_branch_role_contacts(directory, bc)
        if role_emails:
            b['email'] = ", ".join(role_emails)
            b['contact_name'] = "; ".join(role_names)
            b['designation'] = f"{len(role_emails)} role(s): Incharge/Billing/Delivery/DBP"
        else:
            email, name, desig = pick_branch_email(directory, bc)
            b['email'] = email
            b['contact_name'] = name
            b['designation'] = desig
    return report_branches
