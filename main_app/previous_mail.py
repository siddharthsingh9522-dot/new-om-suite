"""
Previous Mail & Format — purani email ka format (TO/CC/BCC/Subject/Body) use karke
naye data se mail banane ke liye helper functions. Ye TBB Party aur Bill Generated Mail
se poori tarah ALAG module hai — apna khud ka workflow hai.
"""

import re
from email import policy
from email.parser import BytesParser, Parser
import pandas as pd


def parse_eml_bytes(raw_bytes):
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    return _extract_fields(msg)


def parse_eml_text(raw_text):
    msg = Parser(policy=policy.default).parsestr(raw_text)
    return _extract_fields(msg)


def _extract_fields(msg):
    to = msg.get('To', '') or ''
    cc = msg.get('Cc', '') or ''
    bcc = msg.get('Bcc', '') or ''
    subject = msg.get('Subject', '') or ''
    body = ''
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                try:
                    body = part.get_content()
                except Exception:
                    continue
                break
        if not body:
            for part in msg.walk():
                if part.get_content_type() == 'text/html':
                    try:
                        body = part.get_content()
                    except Exception:
                        continue
                    break
    else:
        try:
            body = msg.get_content()
        except Exception:
            body = str(msg.get_payload())

    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            fname = part.get_filename()
            if fname:
                attachments.append(fname)

    return {
        'to': to.strip(), 'cc': cc.strip(), 'bcc': bcc.strip(),
        'subject': subject.strip(), 'body': (body or '').strip(),
        'attachments': attachments,
    }


def parse_manual_fields(to, cc, bcc, subject, body):
    return {
        'to': (to or '').strip(), 'cc': (cc or '').strip(), 'bcc': (bcc or '').strip(),
        'subject': (subject or '').strip(), 'body': (body or '').strip(),
        'attachments': [],
    }


def parse_new_data(filepath):
    """Naya data sheet padhta hai — koi bhi columns ho sakte hain, fixed schema nahi hai
    (TBB/Bill ke parser se alag, jinke columns pehle se maloom the)."""
    lower = str(filepath).lower()
    if lower.endswith('.csv'):
        df = pd.read_csv(filepath)
    else:
        df = pd.read_excel(filepath)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def group_by_key(df, key_col):
    """Data ko ek column (jaise Branch Code) ke hisaab se group karta hai."""
    groups = {}
    for _, row in df.iterrows():
        key_val = row[key_col]
        if pd.isna(key_val):
            continue
        try:
            key = str(int(float(key_val)))
        except (ValueError, TypeError):
            key = str(key_val).strip()
        row_dict = {}
        for c in df.columns:
            v = row[c]
            row_dict[c] = '' if pd.isna(v) else v
        groups.setdefault(key, []).append(row_dict)
    return groups


TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def render_template(template_str, row_dict):
    """{{Column Name}} tokens ko row_dict ki matching value se replace karta hai
    (case-insensitive match). Jo token match na ho wo waisa ka waisa reh jata hai
    (taaki user ko pata chal jaye kaunsa column missing hai)."""
    def repl(m):
        col = m.group(1).strip()
        for k, v in row_dict.items():
            if str(k).strip().lower() == col.lower():
                return str(v)
        return m.group(0)
    return TOKEN_RE.sub(repl, template_str or '')


def render_rows_table_text(rows, columns):
    lines = []
    for i, r in enumerate(rows, 1):
        parts = [f"{c}: {r.get(c,'')}" for c in columns]
        lines.append(f"{i}. " + " | ".join(parts))
    return "\n".join(lines)
