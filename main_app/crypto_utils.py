"""
crypto_utils.py — per-user mail/AI credentials ko DB mein PLAIN TEXT ke bajaye
encrypted store karne ke liye chhota helper.

CREDENTIALS_KEY env var (render.yaml mein generateValue: true se Render khud
ek random string bana deta hai) se ek Fernet key derive karte hain. Render ka
generated string zaroori nahi ki already ek valid 32-byte base64 Fernet key ho,
isliye SHA-256 se hamesha exactly 32 bytes bana kar phir base64 karte hain —
isse jo bhi random string mile, ek valid key ban jaati hai.

IMPORTANT: CREDENTIALS_KEY production mein set hone ke baad kabhi mat badlein —
badalne par pehle se saved sab passwords/API keys unreadable ho jayenge (user
ko dobara /settings mein jaake apna data bharna padega).
"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

_RAW_KEY = os.environ.get("CREDENTIALS_KEY", "").strip()

if not _RAW_KEY:
    # Dev fallback ONLY (local testing bina .env ke). Production (Render) mein
    # CREDENTIALS_KEY zaroor set honi chahiye, warna restart ke baad data padha
    # nahi ja sakega — is default se saved credentials restart-safe NAHI hain.
    _RAW_KEY = "dev-only-insecure-key-set-CREDENTIALS_KEY-in-render-env"

_derived = base64.urlsafe_b64encode(hashlib.sha256(_RAW_KEY.encode("utf-8")).digest())
_fernet = Fernet(_derived)


def encrypt(value: str) -> str:
    """Empty/None -> empty string (taaki DB mein blank rahe, encrypt na ho)."""
    if not value:
        return ""
    return _fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str) -> str:
    """Decrypt fail ho (galat key / corrupt data) to chup-chaap khali string deta
    hai — kabhi crash nahi karta, taaki ek kharab row poori app na todh de."""
    if not value:
        return ""
    try:
        return _fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
