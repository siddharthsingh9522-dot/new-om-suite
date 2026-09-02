"""
Branch Detail Finder — ported from the standalone branch_app into a
Blueprint so it can live inside the unified OM Suite app.

Original standalone behaviour is unchanged (same routes, same scraping
logic) — only the url_prefix ("/branch") and the login requirement are new.
"""

import os
import time
import random
import uuid
import threading

import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import (
    Blueprint, render_template, request, jsonify,
    send_file, redirect, url_for, flash
)
from werkzeug.utils import secure_filename

from auth import login_required

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "branch_uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "branch_outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

BRANCH_URL = "http://scmomsanchar.omlogistics.co.in/oracle/query/branch.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": BRANCH_URL,
    "Content-Type": "application/x-www-form-urlencoded",
}
RETRY_COUNT = 4
TIMEOUT = 20
DELAY_RANGE = (1.0, 2.0)
BLOCK_COOLDOWN = 15

branch_bp = Blueprint(
    "branch", __name__,
    url_prefix="/branch",
    template_folder="../templates/branch",
)

JOBS = {}


def fetch_branch(session, code):
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            payload = {
                "bname": "",
                "bcode": code,
                "ctrlcode": "",
                "state": "all",
                "submit": "Search",
            }
            r = session.post(BRANCH_URL, data=payload, timeout=TIMEOUT)

            if r.status_code == 403:
                time.sleep(BLOCK_COOLDOWN)
                continue
            if r.status_code != 200:
                time.sleep(2)
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            table = soup.find("table", class_="table")
            if table:
                tbody = table.find("tbody")
                rows = tbody.find_all("tr") if tbody else []
                for tr in rows:
                    cols = [td.get_text(strip=True) for td in tr.find_all("td")]
                    if len(cols) >= 6 and cols[1]:
                        return ({
                            "SEARCH_CODE": code,
                            "BRANCH_CODE": cols[1],
                            "BRANCH_NAME": cols[2],
                            "ADDRESS": cols[3],
                            "CONTROLLING_BRANCH": cols[4],
                            "GST_NO": cols[5],
                        }, None)
            return (None, "No data returned")
        except Exception:
            time.sleep(2)
            continue

    return (None, "HTTP 403 Blocked / retries exhausted")


@branch_bp.route("/")
@login_required
def index():
    return render_template("branch/index.html")


@branch_bp.route("/lookup", methods=["POST"])
@login_required
def lookup():
    code = (request.form.get("branch_code") or "").strip()
    if not code.isdigit():
        return jsonify({"ok": False, "error": "Valid numeric branch code daalo."})

    session = requests.Session()
    session.headers.update(HEADERS)
    row, reason = fetch_branch(session, code)

    if row:
        return jsonify({"ok": True, "data": row})
    return jsonify({"ok": False, "error": reason or "Data nahi mila is code ke liye."})


@branch_bp.route("/lookup/download", methods=["POST"])
@login_required
def lookup_download():
    data = request.form.to_dict()
    df = pd.DataFrame([data])
    out_path = os.path.join(OUTPUT_DIR, f"branch_{data.get('SEARCH_CODE', 'result')}.xlsx")
    df.to_excel(out_path, index=False)
    return send_file(out_path, as_attachment=True)


@branch_bp.route("/bulk/upload", methods=["POST"])
@login_required
def bulk_upload():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Koi file select nahi ki.")
        return redirect(url_for("branch.index"))

    filename = secure_filename(file.filename)
    job_id = uuid.uuid4().hex[:10]
    saved_path = os.path.join(UPLOAD_DIR, f"{job_id}_{filename}")
    file.save(saved_path)

    JOBS[job_id] = {
        "status": "queued", "total": 0, "done": 0,
        "success": 0, "errors": 0, "output_path": None,
    }

    thread = threading.Thread(target=run_bulk_job, args=(job_id, saved_path), daemon=True)
    thread.start()

    return redirect(url_for("branch.bulk_status_page", job_id=job_id))


def run_bulk_job(job_id, input_path):
    job = JOBS[job_id]
    try:
        df = pd.read_excel(input_path)
        codes = (
            df.iloc[:, 0].dropna().astype(str)
            .str.extract(r"(\d+)")[0].dropna().unique()
        )
        job["total"] = len(codes)
        job["status"] = "running"

        session = requests.Session()
        session.headers.update(HEADERS)

        success_rows, error_rows = [], []
        for code in codes:
            row, reason = fetch_branch(session, code)
            if row:
                success_rows.append(row)
                job["success"] += 1
            else:
                error_rows.append({"SEARCH_CODE": code, "REASON": reason})
                job["errors"] += 1
            job["done"] += 1
            time.sleep(random.uniform(*DELAY_RANGE))

        out_path = os.path.join(OUTPUT_DIR, f"branch_details_{job_id}.xlsx")
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            succ_df = pd.DataFrame(success_rows) if success_rows else pd.DataFrame(
                columns=["SEARCH_CODE", "BRANCH_CODE", "BRANCH_NAME", "ADDRESS", "CONTROLLING_BRANCH", "GST_NO"])
            err_df = pd.DataFrame(error_rows) if error_rows else pd.DataFrame(columns=["SEARCH_CODE", "REASON"])
            summary_df = pd.DataFrame([{
                "Total Branch Codes": len(codes),
                "Success": len(success_rows),
                "Errors/Not Found": len(error_rows),
            }])
            succ_df.to_excel(writer, sheet_name="Success Report", index=False)
            err_df.to_excel(writer, sheet_name="Error Report", index=False)
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

        job["output_path"] = out_path
        job["status"] = "done"
    except Exception as e:
        job["status"] = "failed"
        job["error_message"] = str(e)


@branch_bp.route("/bulk/status-page/<job_id>")
@login_required
def bulk_status_page(job_id):
    if job_id not in JOBS:
        flash("Job nahi mila.")
        return redirect(url_for("branch.index"))
    return render_template("branch/bulk_status.html", job_id=job_id)


@branch_bp.route("/bulk/status/<job_id>")
@login_required
def bulk_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    return jsonify({"ok": True, **job})


@branch_bp.route("/bulk/download/<job_id>")
@login_required
def bulk_download(job_id):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        flash("File abhi ready nahi hai.")
        return redirect(url_for("branch.index"))
    return send_file(job["output_path"], as_attachment=True,
                      download_name="all_branch_details.xlsx")
