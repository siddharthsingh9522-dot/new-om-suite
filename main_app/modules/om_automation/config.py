# ==============================
# OM Automation V2
# config.py
# ==============================
import os
# -----------------------------
# Application
# -----------------------------
APP_NAME = "OM Automation V2"
VERSION = "2.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Data dirs live under the main app's shared data/ folder (not inside the
# package itself) so they behave the same as the other modules and are
# covered by the same .gitignore rule.
_APP_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), "data", "om")
INPUT_DIR = os.path.join(_APP_DATA_DIR, "input")
OUTPUT_DIR = os.path.join(_APP_DATA_DIR, "output")
LOG_DIR = os.path.join(_APP_DATA_DIR, "logs")
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
# -----------------------------
# API
# -----------------------------
CN_API = "https://load.omone.in/utility-service/api/cn-status/{}"
CUSTOMER_API = "https://scmomsanchar.omlogistics.co.in/oracle/query/customer.php?u=55555%22"
GST_API = "https://services.gst.gov.in/services/api/search/taxpayerDetails"
# -----------------------------
# Network
# -----------------------------
TIMEOUT = 30
RETRY_COUNT = 3
MAX_WORKERS = 20
# -----------------------------
# Flask session signing key (needed for the GST captcha flow, which
# tracks each user's in-progress browser session via a signed cookie)
# -----------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "om-automation-v2-dev-key")
# -----------------------------
# GST Portal - captcha-driven search (used by gst_search.py / api/gst_api.py)
#
# The direct GST_API call above can't return real data on its own -
# services.gst.gov.in requires a human-solved captcha before it will
# answer a search, which is why GST results were always failing. This
# section drives the actual portal page in a real (headless) browser
# instead, screenshotting its captcha for the user to type - same
# approach as the standalone tool this was ported from.
# -----------------------------
GST_URL = "https://services.gst.gov.in/services/searchtp"
CAPTCHA_DIR = os.path.join(_APP_DATA_DIR, "captchas")
os.makedirs(CAPTCHA_DIR, exist_ok=True)
# Known element IDs on the GST portal's "Search Taxpayer" page
GST_BOX_ID = "for_gstin"
CAPTCHA_BOX_ID = "fo-captcha"
SEARCH_BUTTON_ID = "lotsearch"
# Labels pulled out of the result page after a search - these are the
# exact label strings used by the real GST portal page.
RESULT_FIELDS = [
    "Legal Name of Business",
    "Trade Name",
    "Effective Date of registration",
    "Constitution of Business",
    "GSTIN / UIN  Status",
    "Taxpayer Type",
    "Other Office",
    "Principal Place of Business",
]
# Extra labels that also appear on the result page, used only to mark
# where one field's text block ends and the next begins - not included
# in the output. Without these, a field like "Taxpayer Type" would
# accidentally swallow the block that sits right after it on the page.
BOUNDARY_ONLY_LABELS = [
    "Administrative Office",
    "Whether Aadhaar Authenticated?",
    "Whether e-KYC Verified?",
    "Additional Trade Name",
    "Nature Of Core Business Activity",
    "Nature of Business Activities",
    "Dealing In Goods and Services",
]
GST_OUTPUT_COLUMNS = ["GSTIN Searched"] + RESULT_FIELDS + ["Remarks", "Raw Text"]
# -----------------------------
# Headers
# -----------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://ops.omone.in",
    "Referer": "https://ops.omone.in/"
}
GST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": "https://services.gst.gov.in/services/searchtp"
}
# -----------------------------
# Smart Header Detection
#
# NOTE: extended to match README's advertised
# "Supported Headers" list (Bill No, Booking No,
# Consignment No were previously missing here).
# -----------------------------
CN_HEADERS = [
    "cn",
    "cn no",
    "cn_no",
    "cn number",
    "manual cn",
    "manual_cn",
    "manualcn",
    "docket",
    "docket no",
    "docket number",
    "lr",
    "lr no",
    "lr number",
    "lorry receipt",
    "billty",
    "billty no",
    "bilty",
    "bilty no",
    "bill no",
    "bill_no",
    "booking no",
    "booking_no",
    "consignment no",
    "consignment_no",
    "consignment number",
    "cn_cn_no",
    "cn cn no",
    "cn_cn_number"
]
# Header aliases for the standalone GST Query page's Excel mode
GSTIN_HEADERS = [
    "gstin",
    "gst no",
    "gst_no",
    "gst number",
    "gst"
]
# Header aliases for the standalone Party Code Query page's Excel mode
PARTY_HEADERS = [
    "party code",
    "party_code",
    "partycode",
    "ccode",
    "code",
    "customer code",
    "customer_code"
]
# -----------------------------
# Excel Output Columns
#
# Full field set now that cn_api / customer_api / gst_api actually
# populate all of it (see api/*.py) - matches the CN -> Customer ->
# GST pipeline used by core/processor.py.
#
# NOTE: keep this list free of duplicate column names. "Package",
# "Bill No" and "Bill Date" were each listed twice before - besides
# being pointless, a duplicate name breaks any lookup/zip that maps
# result dict keys to these columns by name, which is what made
# data silently stop showing after the last edit.
# -----------------------------
REPORT_COLUMNS = [
    "Input Sheet",
    "Input Row",
    "Input Column",
    "CN",
    "Bill No",
    "Bill Date",
    "Remarks",
    "CN Date",
    "Party Code",
    "Party Name",
    "Source Code",
    "Source Branch",
    "Destination Code",
    "Destination Branch",
    "Consignor Code",
    "Consignor Name",
    "Consignee Code",
    "Consignee Name",
    "CN Status",
    "Booking Mode",
    "Freight Mode",
    "Package",
    "Gross Value",
    "Net Value",
    "Charged Weight",
    "Actual Weight",
    "Freight Total",
    "Rate Per KG",
    "FOV",
    "DDR No",
    "Lorry No",
    "Delivery Date",
    "Address",
    "Booking Location",
    "Acc Location",
    "Bill Location",
    "Verify",
    "Customer Type",
    "GST",
    "Customer Status",
    "Master Code",
    "Vendor Code",
    "Mobile",
    "Entered By",
    "Entry Date",
    "GSTIN",
    "Trade Name",
    "Legal Name",
    "GST Status",
    "Registration Date",
    "Business Type",
    "Taxpayer Type",
    "GST Address",
    "State Jurisdiction",
    "Central Jurisdiction",
    "Nature Of Business",
    "E-Invoice",
    "EKYC",
    "Pipeline Stage",
    "API Status",
    "Error"
]
