"""
Miscellaneous small helpers shared across services and routes.
"""
import os
import uuid
from datetime import datetime

from werkzeug.utils import secure_filename


def allowed_excel_file(filename: str, allowed_extensions) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_extensions


def unique_upload_name(original_filename: str) -> str:
    safe_name = secure_filename(original_filename)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    token = uuid.uuid4().hex[:8]
    return f"{stamp}_{token}_{safe_name}"


def ensure_dirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def safe_str(value, default=""):
    if value is None:
        return default
    return str(value).strip()


def paginate(items, page: int, per_page: int):
    page = max(1, page)
    per_page = max(1, min(per_page, 500))
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }
