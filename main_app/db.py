"""
SQLite database layer — users, roles, login attempts.
Chhoti team ke liye bana hai, isliye ek simple file-based DB (SQLite) use kiya hai —
alag se Postgres/MySQL server install karne ki zaroorat nahi.
"""

"""
Database layer — users, roles, login attempts, workflow data, mail
operations, bridge tokens/jobs, per-user Mail+AI credentials.

Do modes:
  - DATABASE_URL set (Render production)  -> Postgres (persists across
    redeploys — Render's free-plan disk is ephemeral, but a Postgres
    database like Neon is not).
  - DATABASE_URL not set (local dev)       -> SQLite file, zero setup.

Har function `?` placeholders wale plain SQL strings likhta hai jaise
pehle SQLite ke liye likhe gaye the — Postgres mode mein ek chhota
connection-wrapper (_PGConnWrapper, neeche) unhe khud `%s` mein badal
deta hai, taaki upar ki saari query strings dono DB ke liye same rahein
aur is migration mein diff chhota rahe.
"""

import sqlite3
import os
import json
import secrets
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

INTEGRITY_ERRORS = [sqlite3.IntegrityError]

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    INTEGRITY_ERRORS.append(psycopg2.IntegrityError)

    class _PGConnWrapper:
        """sqlite3.Connection jaisa hi chhota interface (.execute/.commit/.close)
        taaki neeche ka poora file bina badle chalta rahe."""

        def __init__(self, pg_conn):
            self._conn = pg_conn

        def execute(self, sql, params=()):
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql.replace("?", "%s"), tuple(params))
            return cur

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

INTEGRITY_ERRORS = tuple(INTEGRITY_ERRORS)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def get_conn():
    if USE_POSTGRES:
        return _PGConnWrapper(psycopg2.connect(DATABASE_URL))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    pk = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    if not USE_POSTGRES:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id {pk},
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'pending',
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS audit_log (
            id {pk},
            username TEXT,
            event TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS workflow_data (
            id {pk},
            user_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            source_filename TEXT,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, module),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS mail_operations (
            id {pk},
            user_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            branch_code TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            selected INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, module, branch_code),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_tokens (
            user_id INTEGER PRIMARY KEY,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS bridge_jobs (
            id {pk},
            user_id INTEGER NOT NULL,
            job_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_credentials (
            user_id INTEGER PRIMARY KEY,
            smtp_host TEXT NOT NULL DEFAULT '',
            smtp_port INTEGER NOT NULL DEFAULT 587,
            smtp_user TEXT NOT NULL DEFAULT '',
            smtp_pass_enc TEXT NOT NULL DEFAULT '',
            smtp_from_email TEXT NOT NULL DEFAULT '',
            smtp_from_name TEXT NOT NULL DEFAULT '',
            imap_host TEXT NOT NULL DEFAULT '',
            imap_port INTEGER NOT NULL DEFAULT 993,
            imap_user TEXT NOT NULL DEFAULT '',
            imap_pass_enc TEXT NOT NULL DEFAULT '',
            imap_sent_folder TEXT NOT NULL DEFAULT 'Sent',
            ai_provider TEXT NOT NULL DEFAULT 'none',
            gemini_api_key_enc TEXT NOT NULL DEFAULT '',
            anthropic_api_key_enc TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


def record_audit(username, event, detail=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (username, event, detail, created_at) VALUES (?,?,?,?)",
        (username, event, detail, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def user_count():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()
    return n


def create_user(name, username, email, password):
    """Pehla user automatically admin+active banta hai (bootstrap). Baaki sab 'pending' rehte hain."""
    conn = get_conn()
    is_first = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0
    role = "admin" if is_first else "user"
    status = "active" if is_first else "pending"
    pw_hash = generate_password_hash(password)
    try:
        conn.execute(
            """INSERT INTO users (name, username, email, password_hash, role, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (name, username, email, pw_hash, role, status, datetime.utcnow().isoformat(timespec="seconds")),
        )
        conn.commit()
    except INTEGRITY_ERRORS as e:
        conn.close()
        raise ValueError("Username ya email pehle se registered hai") from e
    conn.close()
    return role, status


def get_user_by_username(username):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_user_status(user_id, status):
    conn = get_conn()
    conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
    conn.commit()
    conn.close()


def set_user_role(user_id, role):
    conn = get_conn()
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    conn.commit()
    conn.close()


def register_failed_attempt(username):
    conn = get_conn()
    row = conn.execute("SELECT failed_attempts FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        conn.close()
        return
    attempts = row["failed_attempts"] + 1
    locked_until = None
    if attempts >= MAX_FAILED_ATTEMPTS:
        locked_until = (datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE username = ?",
        (attempts, locked_until, username),
    )
    conn.commit()
    conn.close()
    return attempts, locked_until


def reset_failed_attempts(username):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = ?",
        (username,),
    )
    conn.commit()
    conn.close()


def is_locked(user_row):
    if not user_row.get("locked_until"):
        return False
    try:
        locked_until = datetime.fromisoformat(user_row["locked_until"])
    except ValueError:
        return False
    return datetime.utcnow() < locked_until


def verify_password(user_row, password):
    return check_password_hash(user_row["password_hash"], password)


# ---------------- Workflow data (user-owned TBB/Bill branch data) ----------------
# module is 'tbb' or 'bill'. One row per (user_id, module) — upload replaces the row.
# Data persists across app restarts, unlike the old in-memory STATE dict.

def save_workflow_data(user_id, module, data_dict, source_filename=""):
    payload = json.dumps(data_dict, ensure_ascii=False, default=str)
    conn = get_conn()
    conn.execute(
        """INSERT INTO workflow_data (user_id, module, source_filename, data, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(user_id, module) DO UPDATE SET
             source_filename = excluded.source_filename,
             data = excluded.data,
             updated_at = excluded.updated_at""",
        (user_id, module, source_filename, payload, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_workflow_data(user_id, module):
    conn = get_conn()
    row = conn.execute(
        "SELECT data FROM workflow_data WHERE user_id = ? AND module = ?",
        (user_id, module),
    ).fetchone()
    conn.close()
    if not row:
        return {}
    return json.loads(row["data"])


# ---------------- Mail operations (selective send / queue / idempotency) ----------------
# One row per (user_id, module, branch_code). Statuses:
#   DRAFT    -> generated, not yet confirmed for sending
#   QUEUED   -> user selected + confirmed, eligible to send
#   SKIPPED  -> user did not select this one; MUST NEVER be sent
#   SENDING  -> send in progress (set right before the SMTP call)
#   SENT     -> delivered successfully; NEVER sent again
#   FAILED   -> send attempt failed; eligible for retry (moves back to QUEUED)
#
# fingerprint = hash of (branch_code + recipient + message content). Same content -> same
# fingerprint -> already-SENT operations are left alone (idempotency / duplicate protection).
# Different content (e.g. a new day's data) -> different fingerprint -> fresh DRAFT operation.

def sync_operations(user_id, module, branch_fingerprints):
    """branch_fingerprints: dict of branch_code -> fingerprint (computed from current data).
    Creates/updates operation rows. Returns dict branch_code -> operation row (as dict)."""
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    for branch_code, fp in branch_fingerprints.items():
        existing = conn.execute(
            "SELECT * FROM mail_operations WHERE user_id=? AND module=? AND branch_code=?",
            (user_id, module, branch_code),
        ).fetchone()
        if existing and existing["fingerprint"] == fp:
            # Same content as before (sent, queued, or still draft) — leave it alone.
            continue
        # New or changed content -> fresh DRAFT operation (selected by default).
        conn.execute(
            """INSERT INTO mail_operations (user_id, module, branch_code, fingerprint, selected, status, attempt_count, created_at, updated_at)
               VALUES (?,?,?,?,1,'DRAFT',0,?,?)
               ON CONFLICT(user_id, module, branch_code) DO UPDATE SET
                 fingerprint = excluded.fingerprint,
                 selected = 1,
                 status = 'DRAFT',
                 attempt_count = 0,
                 last_error = NULL,
                 updated_at = excluded.updated_at""",
            (user_id, module, branch_code, fp, now, now),
        )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM mail_operations WHERE user_id=? AND module=?", (user_id, module)
    ).fetchall()
    conn.close()
    return {r["branch_code"]: dict(r) for r in rows}


def get_operations(user_id, module):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mail_operations WHERE user_id=? AND module=?", (user_id, module)
    ).fetchall()
    conn.close()
    return {r["branch_code"]: dict(r) for r in rows}


def confirm_selection(user_id, module, selected_codes):
    """selected_codes: branch_codes the user ticked. Everything else currently in DRAFT
    becomes SKIPPED and MUST NEVER be sent. Only DRAFT rows are affected — already
    QUEUED/SENT/FAILED rows are untouched by re-confirming."""
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT branch_code, status FROM mail_operations WHERE user_id=? AND module=?",
        (user_id, module),
    ).fetchall()
    selected_set = set(selected_codes)
    for r in rows:
        if r["status"] != "DRAFT":
            continue
        new_status = "QUEUED" if r["branch_code"] in selected_set else "SKIPPED"
        selected_flag = 1 if r["branch_code"] in selected_set else 0
        conn.execute(
            "UPDATE mail_operations SET status=?, selected=?, updated_at=? WHERE user_id=? AND module=? AND branch_code=?",
            (new_status, selected_flag, now, user_id, module, r["branch_code"]),
        )
    conn.commit()
    conn.close()


def mark_sending(user_id, module, branch_code):
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE mail_operations SET status='SENDING', updated_at=? WHERE user_id=? AND module=? AND branch_code=?",
        (now, user_id, module, branch_code),
    )
    conn.commit()
    conn.close()


def mark_sent(user_id, module, branch_code):
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        """UPDATE mail_operations SET status='SENT', last_error=NULL, updated_at=?,
           attempt_count = attempt_count + 1
           WHERE user_id=? AND module=? AND branch_code=?""",
        (now, user_id, module, branch_code),
    )
    conn.commit()
    conn.close()


def mark_failed(user_id, module, branch_code, error):
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        """UPDATE mail_operations SET status='FAILED', last_error=?, updated_at=?,
           attempt_count = attempt_count + 1
           WHERE user_id=? AND module=? AND branch_code=?""",
        (error, now, user_id, module, branch_code),
    )
    conn.commit()
    conn.close()


def retry_failed_to_queued(user_id, module):
    """Moves only FAILED operations back to QUEUED. SENT/SKIPPED/CANCELLED are never touched.
    Returns only the branch_codes that were actually FAILED->QUEUED just now (not the
    full queued list — a previously-queued item must not be reported as 'retried')."""
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    failed_rows = conn.execute(
        "SELECT branch_code FROM mail_operations WHERE user_id=? AND module=? AND status='FAILED'",
        (user_id, module),
    ).fetchall()
    just_retried = [r["branch_code"] for r in failed_rows]
    conn.execute(
        "UPDATE mail_operations SET status='QUEUED', updated_at=? WHERE user_id=? AND module=? AND status='FAILED'",
        (now, user_id, module),
    )
    conn.commit()
    conn.close()
    return just_retried


# ---------------- Thunderbird Bridge (extension <-> web app) ----------------
# Har user ka apna bridge token hota hai (extension Options mein daalne ke liye).
# Extension is token + username ko headers mein bhejta hai — koi session cookie use
# nahi hota (Thunderbird background script browser session share nahi karta).

def get_or_create_bridge_token(user_id):
    conn = get_conn()
    row = conn.execute("SELECT token FROM bridge_tokens WHERE user_id=?", (user_id,)).fetchone()
    if row:
        conn.close()
        return row["token"]
    token = secrets.token_hex(24)
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute("INSERT INTO bridge_tokens (user_id, token, created_at) VALUES (?,?,?)", (user_id, token, now))
    conn.commit()
    conn.close()
    return token


def regenerate_bridge_token(user_id):
    token = secrets.token_hex(24)
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = get_conn()
    conn.execute(
        """INSERT INTO bridge_tokens (user_id, token, created_at) VALUES (?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET token=excluded.token, created_at=excluded.created_at""",
        (user_id, token, now),
    )
    conn.commit()
    conn.close()
    return token


def get_user_by_bridge_auth(username, token):
    """Extension se aaye X-Thunderbird-User aur X-Thunderbird-Token dono match karne
    chahiye — sirf token match karna kaafi nahi (username bhi confirm karta hai ki
    sahi account se request aa rahi hai)."""
    if not username or not token:
        return None
    user = get_user_by_username(username.strip().lower())
    if not user or user["status"] != "active":
        return None
    conn = get_conn()
    row = conn.execute("SELECT token FROM bridge_tokens WHERE user_id=?", (user["id"],)).fetchone()
    conn.close()
    if not row or row["token"] != token:
        return None
    return user


def enqueue_bridge_job(user_id, job_type, payload):
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO bridge_jobs (user_id, job_type, payload, status, created_at, updated_at)
           VALUES (?,?,?,'pending',?,?) RETURNING id""",
        (user_id, job_type, json.dumps(payload, ensure_ascii=False, default=str), now, now),
    )
    job_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return job_id


def poll_bridge_jobs(user_id, limit=5):
    """Pending jobs deta hai aur unhe 'delivered' mark kar deta hai (dobara poll na hon)."""
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT * FROM bridge_jobs WHERE user_id=? AND status='pending' ORDER BY id ASC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE bridge_jobs SET status='delivered', updated_at=? WHERE id IN ({placeholders})",
            (now, *ids),
        )
        conn.commit()
    conn.close()
    return [{"id": r["id"], "job_type": r["job_type"], "payload": json.loads(r["payload"])} for r in rows]


# ---------------- Per-user Mail + AI credentials ----------------
# Har user apni khud ki SMTP/IMAP/AI details "/settings" page se bharta hai —
# ab koi bhi shared/admin ka mail ya API key .env se use nahi hota. Passwords
# aur API keys sirf encrypted (crypto_utils) DB mein save hote hain.

from crypto_utils import encrypt, decrypt

_EMPTY_CREDENTIALS_ROW = {
    "smtp_host": "", "smtp_port": 587, "smtp_user": "", "smtp_pass": "",
    "smtp_from_email": "", "smtp_from_name": "",
    "imap_host": "", "imap_port": 993, "imap_user": "", "imap_pass": "",
    "imap_sent_folder": "Sent",
    "ai_provider": "none", "gemini_api_key": "", "anthropic_api_key": "",
}


def get_user_credentials(user_id):
    """Decrypted config deta hai, do groups mein split kiya hua:
    {'mail': {...}, 'ai': {...}}. Row na ho to sensible empty defaults."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM user_credentials WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        r = dict(_EMPTY_CREDENTIALS_ROW)
    else:
        r = dict(row)
        r["smtp_pass"] = decrypt(r.pop("smtp_pass_enc", ""))
        r["imap_pass"] = decrypt(r.pop("imap_pass_enc", ""))
        r["gemini_api_key"] = decrypt(r.pop("gemini_api_key_enc", ""))
        r["anthropic_api_key"] = decrypt(r.pop("anthropic_api_key_enc", ""))
    return {
        "mail": {
            "smtp_host": r["smtp_host"], "smtp_port": r["smtp_port"],
            "smtp_user": r["smtp_user"], "smtp_pass": r["smtp_pass"],
            "smtp_from_email": r["smtp_from_email"] or r["smtp_user"],
            "smtp_from_name": r["smtp_from_name"],
            "imap_host": r["imap_host"], "imap_port": r["imap_port"],
            "imap_user": r["imap_user"], "imap_pass": r["imap_pass"],
            "imap_sent_folder": r["imap_sent_folder"] or "Sent",
            "configured": bool(r["smtp_host"] and r["smtp_user"] and r["smtp_pass"]),
        },
        "ai": {
            "provider": r["ai_provider"] or "none",
            "gemini_api_key": r["gemini_api_key"],
            "anthropic_api_key": r["anthropic_api_key"],
        },
    }


def save_mail_credentials(user_id, smtp_host, smtp_port, smtp_user, smtp_pass,
                           smtp_from_email, smtp_from_name, imap_host, imap_port,
                           imap_user, imap_pass, imap_sent_folder):
    """Password fields khaali bheje jayein to purana saved password waisa hi
    rehta hai (settings form mein password blank dikhta hai — retype tabhi
    zaroori hai jab change karna ho)."""
    conn = get_conn()
    existing = conn.execute(
        "SELECT smtp_pass_enc, imap_pass_enc FROM user_credentials WHERE user_id = ?", (user_id,)
    ).fetchone()
    smtp_pass_enc = encrypt(smtp_pass) if smtp_pass else (existing["smtp_pass_enc"] if existing else "")
    imap_pass_enc = encrypt(imap_pass) if imap_pass else (existing["imap_pass_enc"] if existing else "")
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO user_credentials
             (user_id, smtp_host, smtp_port, smtp_user, smtp_pass_enc, smtp_from_email,
              smtp_from_name, imap_host, imap_port, imap_user, imap_pass_enc,
              imap_sent_folder, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port,
             smtp_user=excluded.smtp_user, smtp_pass_enc=excluded.smtp_pass_enc,
             smtp_from_email=excluded.smtp_from_email, smtp_from_name=excluded.smtp_from_name,
             imap_host=excluded.imap_host, imap_port=excluded.imap_port,
             imap_user=excluded.imap_user, imap_pass_enc=excluded.imap_pass_enc,
             imap_sent_folder=excluded.imap_sent_folder, updated_at=excluded.updated_at""",
        (user_id, smtp_host, smtp_port, smtp_user, smtp_pass_enc, smtp_from_email,
         smtp_from_name, imap_host, imap_port, imap_user, imap_pass_enc,
         imap_sent_folder, now),
    )
    conn.commit()
    conn.close()


def save_ai_credentials(user_id, ai_provider, gemini_api_key, anthropic_api_key):
    """Yahan bhi: key field khaali bheje jayein to purani saved key retain hoti hai."""
    conn = get_conn()
    existing = conn.execute(
        "SELECT gemini_api_key_enc, anthropic_api_key_enc FROM user_credentials WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    gemini_enc = encrypt(gemini_api_key) if gemini_api_key else (existing["gemini_api_key_enc"] if existing else "")
    anthropic_enc = encrypt(anthropic_api_key) if anthropic_api_key else (existing["anthropic_api_key_enc"] if existing else "")
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO user_credentials (user_id, ai_provider, gemini_api_key_enc, anthropic_api_key_enc, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             ai_provider=excluded.ai_provider,
             gemini_api_key_enc=excluded.gemini_api_key_enc,
             anthropic_api_key_enc=excluded.anthropic_api_key_enc,
             updated_at=excluded.updated_at""",
        (user_id, ai_provider, gemini_enc, anthropic_enc, now),
    )
    conn.commit()
    conn.close()


def store_bridge_job_result(job_id, user_id, result=None, status="done", error=None):
    conn = get_conn()
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        """UPDATE bridge_jobs SET status=?, result=?, error=?, updated_at=?
           WHERE id=? AND user_id=?""",
        (status, json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
         error, now, job_id, user_id),
    )
    conn.commit()
    conn.close()


def get_bridge_job(job_id, user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM bridge_jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result"):
        d["result"] = json.loads(d["result"])
    return d


def list_recent_bridge_jobs(user_id, limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bridge_jobs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("result"):
            d["result"] = json.loads(d["result"])
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out
