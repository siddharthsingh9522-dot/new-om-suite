"""
Gemini AI copilot - ADVISORY ONLY.

This service NEVER saves, modifies, or bypasses user confirmation. It only
analyzes a proposed modification (single CN or a bulk batch summary) and
returns a structured risk/findings report for display in an "AI Assistant"
panel. The actual Confirm/Modify button is always a separate, explicit
user action regardless of what this returns.

Only non-sensitive context is ever sent to Gemini: CN number, party/value
codes, and remark text. Credentials, tokens, and cookies are NEVER
included in the prompt.

If GEMINI_API_KEY is not configured, or the call fails/times out for any
reason, this degrades to a neutral "AI assistant not available" result -
it must never raise an exception that could interrupt the modification
workflow.
"""
import json
import logging

import requests

from config import settings

logger = logging.getLogger("gr_auto_mod.ai_service")

_NOT_CONFIGURED_RESULT = {
    "available": False,
    "risk_level": None,
    "status": "AI_NOT_CONFIGURED",
    "findings": [],
    "warnings": [],
    "errors": [],
    "recommendation": "AI assistant is not configured (GEMINI_API_KEY not set). Proceeding without AI analysis.",
}


def _neutral_error_result(reason: str) -> dict:
    return {
        "available": False,
        "risk_level": None,
        "status": "AI_UNAVAILABLE",
        "findings": [],
        "warnings": [],
        "errors": [],
        "recommendation": f"AI assistant could not complete analysis ({reason}). Proceeding without AI analysis.",
    }


def ai_configured() -> bool:
    return bool(settings.GEMINI_API_KEY)


def _build_prompt(context: dict) -> str:
    # Only safe, non-sensitive fields make it into the prompt.
    safe_context = {
        "module": context.get("module"),
        "gr_number": context.get("gr_number"),
        "current_value": context.get("current_value"),
        "new_value": context.get("new_value"),
        "existing_remark": context.get("existing_remark"),
        "new_remark": context.get("new_remark"),
        "proposed_final_remark": context.get("proposed_final_remark"),
        "change_type": context.get("change_type"),
    }
    return (
        "You are a careful reviewing assistant for a logistics CN/GR modification tool. "
        "Analyze the following proposed change and return ONLY a JSON object "
        "with exactly these keys: risk_level (LOW/MEDIUM/HIGH), findings (array "
        "of short strings), warnings (array of short strings), errors (array of "
        "short strings), recommendation (one short string). Do not include any "
        "text outside the JSON object.\n\n"
        f"Proposed change:\n{json.dumps(safe_context, indent=2, default=str)}"
    )


def analyze_modification_request(context: dict) -> dict:
    """
    Ask Gemini to analyze a proposed single-CN or bulk-summary modification.
    Always returns a dict with the keys shown in _NOT_CONFIGURED_RESULT,
    never raises.
    """
    if not ai_configured():
        return dict(_NOT_CONFIGURED_RESULT)

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": _build_prompt(context)}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    try:
        response = requests.post(url, json=body, timeout=settings.GEMINI_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except requests.Timeout:
        logger.warning("Gemini AI analysis timed out")
        return _neutral_error_result("request timed out")
    except requests.RequestException as exc:
        logger.warning("Gemini AI analysis request failed: %s", exc)
        return _neutral_error_result("request failed")
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Gemini AI analysis returned an unexpected shape: %s", exc)
        return _neutral_error_result("unexpected response shape")

    return {
        "available": True,
        "risk_level": parsed.get("risk_level", "LOW"),
        "status": "SAFE_TO_REVIEW",
        "findings": parsed.get("findings", []) or [],
        "warnings": parsed.get("warnings", []) or [],
        "errors": parsed.get("errors", []) or [],
        "recommendation": parsed.get("recommendation", ""),
    }


def explain_error(technical_error: str, gr_number: str = "") -> dict:
    """
    Ask Gemini for a plain-language explanation of a technical API error.
    Degrades to a static, still-useful message if AI is unavailable.
    """
    if not ai_configured():
        return {
            "available": False,
            "explanation": technical_error,
            "likely_cause": "AI assistant not configured for a plain-language explanation.",
            "recommended_action": "Check the CN number and retry, or skip this record.",
        }

    context = {
        "gr_number": gr_number,
        "technical_error": technical_error,
    }
    prompt = (
        "Explain this technical error from a logistics CN modification API in "
        "plain language for a non-technical operator. Return ONLY a JSON object "
        "with keys: explanation, likely_cause, recommended_action.\n\n"
        f"{json.dumps(context, default=str)}"
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    try:
        response = requests.post(url, json=body, timeout=settings.GEMINI_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        return {
            "available": True,
            "explanation": parsed.get("explanation", technical_error),
            "likely_cause": parsed.get("likely_cause", ""),
            "recommended_action": parsed.get("recommended_action", ""),
        }
    except Exception as exc:  # noqa: BLE001 - AI explanation is best-effort only
        logger.warning("Gemini error-explanation call failed: %s", exc)
        return {
            "available": False,
            "explanation": technical_error,
            "likely_cause": "AI assistant could not analyze this error.",
            "recommended_action": "Check the CN number and retry, or skip this record.",
        }
