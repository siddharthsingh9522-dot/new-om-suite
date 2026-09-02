"""Auto Bill Generated Mail parsing and email formatting."""
import html
import re
import pandas as pd

BILL_COL_KEYWORDS = {
    'branch_code': ['B. CODE', 'B.CODE', 'BRANCH CODE', 'BCODE'],
    'branch_name': ['BRANCH'], 'region': ['REGION'], 'cn': ['CN'],
    'bill_no': ['BILL NO', 'BILL NUMBER', 'BILLNO'], 'cn_date': ['CN DATE'],
    'party_code': ['PARTY CODE'], 'party_name': ['PARTY NAME'],
    'source_code': ['SOURCE CODE'], 'source_branch': ['SOURCE BRANCH'],
    'destination_code': ['DESTINATION CODE'], 'destination_branch': ['DESTINATION BRANCH'],
    'consignor_code': ['CONSIGNOR CODE'], 'consignor_name': ['CONSIGNOR NAME'],
    'consignee_code': ['CONSIGNEE CODE'], 'consignee_name': ['CONSIGNEE NAME'],
    'cn_status': ['CN STATUS'], 'booking_mode': ['BOOKING MODE'], 'freight_mode': ['FREIGHT MODE'],
    'package': ['PACKAGE'], 'gross_value': ['GROSS VALUE'], 'net_value': ['NET VALUE'],
    'charged_weight': ['CHARGED WEIGHT'], 'actual_weight': ['ACTUAL WEIGHT'],
    'freight_total': ['FREIGHT TOTAL'], 'rate_per_kg': ['RATE PER KG'], 'fov': ['FOV'],
    'ddr_no': ['DDR NO'], 'lorry_no': ['LORRY NO'], 'delivery_date': ['DELIVERY DATE'],
}
DISPLAY_COLS = [
    ('branch_code','B.Code'),('branch_name','Branch'),('region','Region'),('cn','CN'),('bill_no','Bill No'),
    ('cn_date','CN Date'),('party_code','Party Code'),('party_name','Party Name'),('source_branch','Source Branch'),
    ('destination_branch','Destination Branch'),('consignor_name','Consignor Name'),('consignee_name','Consignee Name'),
    ('cn_status','CN Status'),('package','Package'),('gross_value','Gross Value'),('charged_weight','Charged Weight'),
    ('freight_total','Freight Total'),('ddr_no','DDR No'),('lorry_no','Lorry No'),('delivery_date','Delivery Date')
]

def _match_column(columns, keywords):
    normalized={c: re.sub(r'\s+',' ',str(c).upper().strip()) for c in columns}
    for kw in keywords:
        for c,u in normalized.items():
            if u == kw: return c
    for kw in keywords:
        for c,u in normalized.items():
            if kw in u: return c
    return None

def _clean(v):
    if v is None or (isinstance(v,float) and pd.isna(v)): return ''
    return str(v).strip()

def _branch_code(v):
    v=_clean(v)
    if not v: return ''
    try: return str(int(float(v)))
    except (ValueError,TypeError): return v

def parse_bill_report(filepath, sheet_name=0):
    df=pd.read_excel(filepath,sheet_name=sheet_name)
    col_map={k:_match_column(df.columns.tolist(),kws) for k,kws in BILL_COL_KEYWORDS.items()}
    if col_map['branch_code'] is None: raise ValueError("Sheet mein 'B. Code' / 'Branch Code' jaisa column nahi mila.")
    if col_map['bill_no'] is None: raise ValueError("Sheet mein 'Bill No' jaisa column nahi mila.")
    branches={}
    for _,row in df.iterrows():
        bc=_branch_code(row[col_map['branch_code']])
        if not bc: continue
        if bc not in branches:
            branches[bc]={'branch_code':bc,'branch_name_sheet':_clean(row[col_map['branch_name']]) if col_map['branch_name'] else '',
                          'region':_clean(row[col_map['region']]) if col_map['region'] else '','bills':[]}
        bill={}
        for key,_label in DISPLAY_COLS:
            col=col_map.get(key)
            bill[key]=_clean(row[col]) if col is not None else ''
        branches[bc]['bills'].append(bill)
    return branches

def build_subject(branch):
    bills=branch.get('bills',[])
    nos=[_clean(b.get('bill_no')) for b in bills if _clean(b.get('bill_no'))]
    bill_range=nos[0] if len(nos)==1 else f"{nos[0]}/{nos[-1]}" if nos else ''
    seen=set(); parties=[]
    for b in bills:
        name=_clean(b.get('party_name'))
        if name and name not in seen: seen.add(name); parties.append(name)
    return f"SCM Retail Express:-Bill No.- {bill_range} Auto Generated Freight Bill For The M/S:-{','.join(parties)}"

BODY_INTRO_TEXT=(
    "Dear Concern,\n\n"
    "Please note subjected Auto generated Tax Invoice.\n\n"
    "If have you any issue let us know within 20 hours from now.\n\n"
)
BODY_INTRO_HTML=(
    "<p>Dear Concern,</p>"
    "<p>Please note subjected Auto generated Tax Invoice.</p>"
    "<p>If have you any issue let us know within 20 hours from now.</p>"
)

def build_table_html(branch):
    headers=''.join(f'<th style="background:#1F4E78;color:#fff;padding:6px 8px;font-size:11px;border:1px solid #ccc;">{html.escape(label)}</th>' for _,label in DISPLAY_COLS)
    rows=[]
    for i,b in enumerate(branch.get('bills',[])):
        bg='#E2EFDA' if i%2==0 else '#FFFFFF'
        cells=''.join(f'<td style="padding:5px 8px;font-size:11px;border:1px solid #ccc;background:{bg};">{html.escape(_clean(b.get(key)))}</td>' for key,_ in DISPLAY_COLS)
        rows.append(f'<tr>{cells}</tr>')
    return '<table style="border-collapse:collapse;font-family:Arial,sans-serif;"><thead><tr>'+headers+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table>'

def build_table_text(branch):
    return '\n'.join(f"{i}. CN: {_clean(b.get('cn'))} | Bill No: {_clean(b.get('bill_no'))} | Party: {_clean(b.get('party_name'))} | Freight Total: {_clean(b.get('freight_total'))}" for i,b in enumerate(branch.get('bills',[]),1))

def build_email_html(branch):
    return f"<html><body style='font-family:Arial,sans-serif;font-size:13px;'>{BODY_INTRO_HTML}{build_table_html(branch)}</body></html>"

def build_email_text(branch):
    return BODY_INTRO_TEXT + build_table_text(branch)


def build_attachment_csv(branch):
    import io, csv as csv_mod
    buf = io.StringIO()
    writer = csv_mod.writer(buf)
    writer.writerow([label for _, label in DISPLAY_COLS])
    for b in branch.get('bills', []):
        writer.writerow([_clean(b.get(key)) for key, _ in DISPLAY_COLS])
    return buf.getvalue().encode("utf-8")
