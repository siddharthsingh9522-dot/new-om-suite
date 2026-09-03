# ==========================================
# OM Automation V2
# gst_search.py
#
# Real GST portal automation (services.gst.gov.in) via a headless
# Chrome browser. This is the part api/gst_api.py was missing: the
# portal's search requires a human-solved captcha, so a plain
# requests.post() (what the old gst_api.py did) can never return real
# data - it just gets rejected by the portal every time. This module
# never tries to auto-solve or bypass the captcha - it screenshots it
# so the user can type it, same as the proven standalone tool this
# was ported from.
# ==========================================

import os
import re
import time

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    # selenium / webdriver-manager (and a working Chrome install) are only
    # needed for the GST-captcha flow. Everything else in this app (CN,
    # Party, Branch, Customer, TBB Mail, Bill Mail...) works fine without
    # them, so we don't want a missing Chrome/selenium setup to crash the
    # whole app on import. See the top-level README for the Render note
    # about deploying this module with Chrome available.
    SELENIUM_AVAILABLE = False

from modules.om_automation.config import (
    GST_URL, GST_BOX_ID, CAPTCHA_BOX_ID, SEARCH_BUTTON_ID,
    RESULT_FIELDS, BOUNDARY_ONLY_LABELS,
)


def open_browser():
    if not SELENIUM_AVAILABLE:
        raise RuntimeError(
            "GST captcha search needs Selenium + Chrome, which aren't "
            "available on this server. Run this feature on a machine/"
            "service that has Chrome + chromedriver installed."
        )
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1366,900")

    chrome_bin = os.environ.get("CHROME_BIN")
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
    if chrome_bin:
        options.binary_location = chrome_bin

    if chromedriver_path:
        # Docker image already ships a matching chromium + chromedriver pair
        # (see Dockerfile) — use it directly instead of webdriver-manager,
        # which would otherwise try to download a driver at runtime (slow,
        # and can pick a version that doesn't match the installed browser).
        driver = webdriver.Chrome(service=Service(chromedriver_path), options=options)
    else:
        # Local/dev fallback: no CHROMEDRIVER_PATH set, so let
        # webdriver-manager figure out and download a matching driver.
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )
    return driver


def go_to_search_page(driver):
    driver.get(GST_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, GST_BOX_ID))
    )


def fill_gst(driver, gst):
    box = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.ID, GST_BOX_ID))
    )
    box.clear()
    box.send_keys(gst)


def find_captcha_element(driver):
    """
    The portal doesn't expose a documented stable ID for the captcha
    image, so we look for anything that plausibly is one, in order of
    likelihood.
    """
    xpaths = [
        "//img[contains(@id,'captcha') or contains(@class,'captcha') or contains(@src,'captcha')]",
        "//canvas[contains(@id,'captcha') or contains(@class,'captcha')]",
        "//*[contains(@id,'captcha') and (self::img or self::canvas or self::div)]",
    ]
    for xp in xpaths:
        elements = driver.find_elements(By.XPATH, xp)
        if elements:
            return elements[0]
    return None


def screenshot_captcha(driver, save_path):
    """
    Screenshots just the captcha element if we can find it, otherwise
    falls back to a screenshot of the visible page so the user can
    still read it manually and the flow doesn't break.
    """
    time.sleep(0.3)  # let the captcha image finish rendering
    el = find_captcha_element(driver)
    if el is not None:
        try:
            el.screenshot(save_path)
            return True
        except Exception:
            pass
    driver.save_screenshot(save_path)
    return False


def fill_captcha(driver, text):
    box = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.ID, CAPTCHA_BOX_ID))
    )
    box.clear()
    box.send_keys(text)


def click_search(driver, timeout=10):
    btn = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.ID, SEARCH_BUTTON_ID))
    )
    before_text = driver.find_element(By.TAG_NAME, "body").text
    btn.click()
    try:
        # Exit as soon as the page actually changes (usually faster
        # than a flat wait), instead of always waiting the full time.
        WebDriverWait(driver, timeout).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != before_text
        )
    except Exception:
        pass
    time.sleep(0.3)  # small buffer for the last bit of rendering


def get_page_text(driver):
    return driver.find_element(By.TAG_NAME, "body").text


def looks_like_wrong_captcha(page_text):
    lowered = page_text.lower()
    markers = ["invalid captcha", "captcha is not correct", "captcha entered is wrong"]
    return any(m in lowered for m in markers)


def looks_like_error(page_text):
    lowered = page_text.lower()
    markers = [
        "invalid captcha",
        "please enter valid",
        "no record found",
        "invalid gstin",
        "captcha is not correct",
        "something went wrong",
    ]
    return any(m in lowered for m in markers)


def _label_pattern(label):
    """Turn a label into a regex that tolerates the portal's occasional
    double-spacing (e.g. 'GSTIN / UIN  Status') without needing an
    exact-whitespace match."""
    parts = label.split()
    return r"\s+".join(re.escape(p) for p in parts)


def extract_result(driver, gstin_searched):
    page_text = get_page_text(driver)
    result = {"GSTIN Searched": gstin_searched, "Raw Text": page_text[:2000]}

    if looks_like_error(page_text):
        result["Remarks"] = "Error / No data - GSTIN or captcha issue, please recheck manually"
        return result

    # Find where every known label (both the ones we want, and the
    # extra ones used only as boundaries) sits in the page text, so we
    # can slice out exactly the text that belongs to each wanted field
    # - including multi-line ones like "Other Office".
    all_labels = RESULT_FIELDS + BOUNDARY_ONLY_LABELS
    positions = []
    for label in all_labels:
        m = re.search(_label_pattern(label), page_text)
        if m:
            positions.append((m.start(), m.end(), label))
    positions.sort(key=lambda p: p[0])

    for i, (start, end, label) in enumerate(positions):
        if label not in RESULT_FIELDS:
            continue
        next_start = positions[i + 1][0] if i + 1 < len(positions) else len(page_text)
        raw_value = page_text[end:next_start]
        lines = [ln.strip() for ln in raw_value.splitlines() if ln.strip()]
        result[label] = "; ".join(lines) if lines else ""

    found_fields = [f for f in RESULT_FIELDS if f in result]
    result["Remarks"] = "OK" if found_fields else "Could not auto-extract fields - check Raw Text column"
    return result


def close_browser(driver):
    try:
        driver.quit()
    except Exception:
        pass
