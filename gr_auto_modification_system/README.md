# GR Auto Modification System

An internal operations tool for updating CN/GR/Docket/LR remarks and billing party codes,
in both single-record and bulk-Excel modes, with a full preview → confirm → execute workflow,
live progress tracking, retries, audit history, and downloadable Excel reports.

> **Terminology:** GR = CN = Docket = LR. These all refer to the same shipment/document
> identifier throughout the system.

---

## 1. Feature Summary

- **Single CN mode**: enter one GR/CN number + a remark, preview the computed change, confirm.
- **Bulk Excel mode**: upload a workbook, auto-detect (or manually pick) the GR column and the
  Party Code embedded in a common remark, fetch every record's current state, review an advanced
  sortable/filterable preview table, then execute with live progress, pause/resume/stop, and retry.
- **Remark merge logic**: new remark is always prepended to the existing remark, with duplicate
  detection so the same remark is never applied twice (`ALREADY_APPLIED`).
- **Safety-first**: nothing is ever modified during preview/dry-run. The real save/update API is
  intentionally NOT invented — see [Section 6](#6-configuring-the-real-save-api) — until then, all
  "confirm" actions run in Preview/Dry-Run mode and clearly say so.
- **Audit trail & rollback-readiness**: every batch and item is persisted (SQLite by default,
  Postgres-ready), original API snapshots are stored before any change, and a full multi-sheet
  Excel report can be downloaded after every run.

---

## 2. Project Structure

```
gr_auto_modification_system/
├── app.py                     # Flask application factory / entrypoint
├── requirements.txt
├── .env.example
├── config/
│   ├── settings.py            # All configuration, read from environment variables
│   └── modules_config.py      # Registry for Consignor/Consignee/Freight/Transport modules
├── services/
│   ├── api_client.py          # Low-level HTTP client: auth, retry, backoff, rate limiting
│   ├── cn_service.py          # GET /manual-cn/modification/{CN}
│   ├── party_service.py       # GET /manual-cn/details/{PARTY_CODE}
│   ├── modification_service.py# Billing Party: preview, payload builder, save_modification()
│   ├── batch_service.py       # Billing Party: batch orchestration, pause/resume/stop, retries
│   ├── generic_modifier_service.py  # Same as above, generic - for the 4 new modules
│   ├── generic_batch_service.py     # Same as above, generic - for the 4 new modules
│   ├── auth_service.py        # Login / isModifier / allowbulk / session handling
│   ├── ai_service.py          # Gemini AI copilot (advisory only)
│   └── excel_service.py       # Excel parsing, column detection, report generation
├── models/
│   ├── database.py             # DB init + lightweight auto-migration for new columns
│   ├── batch.py, batch_item.py         # Billing Party's own tables (untouched)
│   ├── module_batch.py, module_batch_item.py  # Shared tables for the 4 new modules
│   ├── audit_log.py, app_setting.py
├── routes/
│   ├── dashboard.py, single_cn.py, bulk.py, history.py, api.py, settings_routes.py
│   ├── auth.py                 # /auth/login, /auth/logout, /auth/status
│   └── modules.py              # Generic single+bulk routes for the 4 new modules
├── utils/
│   ├── validators.py, remark_parser.py, retry.py, helpers.py
│   └── auth_decorators.py      # login_required / modifier_required_api / bulk_allowed_required_api
├── templates/                  # Jinja2 templates (Bootstrap 5 UI)
│   ├── module_single.html, module_bulk.html   # Generic pages for the 4 new modules
│   └── login.html
├── static/css/app.css, static/js/app.js, static/js/bulk.js
│   └── static/js/module_single.js, static/js/module_bulk.js
├── samples/gr_bulk_upload_template.xlsx
├── uploads/                   # uploaded Excel files land here (gitignored)
├── exports/                   # generated reports land here (gitignored)
└── tests/
```

---

## 3. Installation

Requires **Python 3.8 or newer**. `requirements.txt` pins `pandas==2.0.3` specifically
so the project installs cleanly on Python 3.8 (pandas 2.1+ requires Python 3.9+). If your
server runs Python 3.9+, you can bump pandas to a newer 2.x release if you prefer.

```bash
cd gr_auto_modification_system
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# edit .env: at minimum set SECRET_KEY, and API_AUTH_MODE / API_BEARER_TOKEN or
# API_SESSION_COOKIE if the upstream API requires authentication.
```

If `pip install` reports a version-resolution error partway through, it means one of the
pins doesn't have a build for your Python/OS combination — later packages in the file may
not get installed even if they'd otherwise work. Re-run `pip install -r requirements.txt`
after fixing the offending pin; don't assume a partial run installed everything above the
failure.

## 4. Running locally

Use `python3`, not `python` — many Linux distributions (including Debian/Ubuntu) don't
alias `python` to Python 3 unless `python-is-python3` is installed.

```bash
python3 app.py
# Flask dev server starts on http://localhost:5000
```

Or with Gunicorn (production-style):

```bash
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
```

The SQLite database (`gr_auto_mod.db`) is created automatically on first run and survives
restarts. Batch/item/audit history is never lost between runs.

---

## 5. How the modification logic works

1. User supplies a **new remark**, e.g. `C0DE 838219 @halol_acc dt22/08/2026 &`
2. The system extracts the **Party Code** (`838219`) using a case-insensitive regex that
   tolerates `CODE`, `C0DE`, `COD3`, with `:`, `-`, or plain whitespace separators
   (see `utils/remark_parser.py`). If nothing is found, the user is prompted to enter it
   manually, and it is validated against the party API before anything proceeds.
3. The system fetches the CN's current `cnRemarks` and `cnBillingPartyCode`.
4. **Final remark rule:** `FINAL_REMARK = NEW_REMARK + " " + EXISTING_REMARK` (new remark first).
   If the existing remark is empty, `FINAL_REMARK = NEW_REMARK`.
5. **Duplicate protection:** if the existing remark already starts with the (normalized) new
   remark, the record is marked `ALREADY_APPLIED` and is never re-prepended.
6. Every record shows a full before/after preview; nothing is modified until the user explicitly
   confirms (single CN) or types `MODIFY <N>` and clicks Execute (bulk).

---

## 6. Configuring the real Save API

The exact endpoint, HTTP method, and payload shape for actually **saving** a modification were
not provided and have **not** been invented or guessed anywhere in this codebase. Everything is
built around a clean seam so the real integration can be dropped in without touching the rest of
the application:

- `services/modification_service.py` → **`save_modification(gr_number, payload)`** is the single
  call-site. Until configured, it always returns `{"success": False, "configured": False, ...}`
  and the UI clearly states *"Save API is not configured yet."* No record is ever silently marked
  as successfully modified.
- `services/modification_service.py` → **`build_modification_payload(existing_data, party_data,
  final_remark)`** builds the payload, preserving 100% of the original CN record (including
  `invoices`) and only overlaying `cnRemarks` / `cnBillingPartyCode` / `cnBillingPartyName`.
  Adapt the `changes` / `full_record` shape here once you capture the real Network request.
- `services/api_client.py` → **`ApiClient.send(method, path, json_payload)`** is the generic
  transport already wired for retries, timeouts, and auth — reuse it for the save call.

**To wire in the real API once you have it:**

1. Capture the exact request from your browser's Network tab (method, URL, headers, payload).
2. In `.env`, set:
   ```
   SAVE_API_ENABLED=true
   SAVE_API_URL=/exact/path/from/capture
   SAVE_API_METHOD=POST   # or PUT/PATCH, whatever was captured
   ```
3. If the save call needs different auth than the read APIs, extend `SAVE_API_AUTH_MODE` handling
   inside `services/api_client.py`.
4. Update `save_modification()` to send exactly the payload shape observed, using
   `api_client.send(...)`.

Until step 2 is done, **Preview and Dry-Run modes work completely** — every other feature
(fetching, validating, previewing, bulk review, exporting) is fully functional with no mocking.

---

## 7. Security notes

- No password, cookie, token, or API secret is hardcoded anywhere — everything comes from
  environment variables (`.env`, never committed).
- CSRF protection is enabled by default for traditional form posts (`Flask-WTF`); JSON API routes
  are called via same-origin `fetch()`.
- All upstream calls have configurable timeouts, retry counts, and exponential backoff, with a
  simple rate limiter to avoid overloading the upstream API during bulk runs.
- Sensitive credentials are never exposed to the frontend or shown on the Settings page.

---

## 8. Known limitations / next steps

- Pause/resume/stop control state is kept in-process (fine for a single Gunicorn worker; move to
  Redis/shared storage for multi-worker deployments).
- Rollback is **snapshot-only** — the app stores the original record for audit purposes, but true
  automatic rollback requires the upstream system to expose a compatible restore/update API.
- The Settings page's runtime values (timeout, retries, concurrency) are stored for visibility;
  wire them fully into `config.settings` at request time if you want them to take effect without
  an app restart.

---

## 9. New modules: Consignor, Consignee, Freight Mode, Transport Mode

Four additional modules live alongside Billing Party, each with its own Single CN + Bulk Excel
pages, reachable from the sidebar/dashboard cards. **Billing Party's own code
(`routes/single_cn.py`, `routes/bulk.py`, `services/modification_service.py`,
`services/batch_service.py`, `models/batch.py`, `models/batch_item.py`) is untouched** - the four
new modules run on a completely separate, generic engine so nothing about Billing Party's
behavior or data can be affected by them:

- `config/modules_config.py` — the module registry. Adding a new module (or changing which CN
  fields Consignor/Consignee/Freight/Transport read and write) is a config change here, not new
  code, because every module shares:
- `services/generic_modifier_service.py` — fetch/preview/payload-build/save/verify, parameterized
  by module config (mirrors `services/modification_service.py`'s design for Billing Party).
- `services/generic_batch_service.py` — bulk orchestration (concurrency, pause/resume/stop,
  retries, post-save verification), mirrors `services/batch_service.py`.
- `models/module_batch.py` / `models/module_batch_item.py` — **separate database tables**
  (`module_batches` / `module_batch_items`) from Billing Party's `batches` / `batch_items`.
- `routes/modules.py` — one set of routes mounted at `/modify/<module_key>/...` for all four.

**Freight Mode / Transport Mode code tables are not guessed.** The real mapping from the
upstream's integer codes (`cnFreightPaidMode`, `cnTptrMode`) to human labels (e.g. "TO PAY",
"SURFACE") was not available when this was built. Each dropdown ships fully usable with raw
codes and a "(label not yet confirmed)" placeholder; set `FREIGHT_MODE_OPTIONS` /
`TRANSPORT_MODE_OPTIONS` in `.env` (JSON array of `{"value":..., "label":...}`) once the real
table is confirmed from the live UI - see `config/modules_config.py` for the exact format.

**Post-save verification** (all five modules, once a real save endpoint is configured): a 200-OK
response from the save call is never enough on its own. `verify_after_save_generic()` /
`verify_after_save()` re-fetch the CN afterward and compare the expected vs. actual value and
remark; only a match is marked `VERIFIED_SUCCESS`, a mismatch is `VERIFICATION_FAILED` with both
values stored for audit.

---

## 10. Authentication & permissions

`services/auth_service.py` wraps the existing upstream login system:

- `POST /manual-cn/login` (via `services.auth_service.login()`) - never hardcodes or logs the
  password; session state (`isModifier`, branch, display name) is stored in Flask's signed
  server-side session cookie only.
- `GET /manual-cn/allowbulk/{branchCode}` (via `check_allow_bulk()`) - **fails closed**: any
  error checking this defaults to bulk being disallowed, never silently permitted.
- `utils/auth_decorators.py` enforces the permission matrix on the actual modify actions only
  (preview/read-only browsing is never blocked):

  | Modifier? | Bulk Allowed? | Single Modify | Bulk Modify |
  |---|---|---|---|
  | No | N/A | blocked | blocked |
  | Yes | No | allowed | blocked |
  | Yes | Yes | allowed | allowed |

Login is optional for browsing/previewing - `/auth/login` is reachable from the topbar, and
"Continue without logging in" is always available for preview-only use.

---

## 11. Gemini AI copilot (advisory only)

`services/ai_service.py` calls Gemini to analyze a proposed change and return structured
`risk_level` / `findings` / `warnings` / `errors` / `recommendation` for display in an "AI
Assistant" panel (Single CN pages for the new modules). **It never saves, modifies, or bypasses
the Confirm button** - it is purely advisory, and only non-sensitive context (CN number, code/
value, remark text) is ever sent to it; credentials and tokens never are.

Set `GEMINI_API_KEY` in `.env` to enable it - everything else works identically whether or not
it's configured, and any AI failure (timeout, malformed response, missing key) degrades to a
neutral "AI assistant not available" result rather than blocking the workflow.

```
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash   # verify this matches what your API key has access to
```
