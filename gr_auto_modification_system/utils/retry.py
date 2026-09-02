"""
Retry / exponential backoff utilities for calling the upstream API.

Uses `tenacity` under the hood but wraps it so the rest of the codebase
only depends on this module (easier to swap implementations later).
"""
import logging

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger("gr_auto_mod.retry")


class PermanentAPIError(Exception):
    """Raised for errors that should NOT be retried (4xx validation errors)."""


class TemporaryAPIError(Exception):
    """Raised for errors that SHOULD be retried (timeouts, 5xx, connection errors)."""


def build_retry_decorator(retry_count: int, backoff_base: float):
    """
    Build a tenacity retry decorator configured from application settings.
    Only TemporaryAPIError (and low-level network errors) trigger a retry;
    PermanentAPIError propagates immediately.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(max(1, retry_count)),
        wait=wait_exponential(multiplier=backoff_base, min=backoff_base, max=30),
        retry=retry_if_exception_type(
            (TemporaryAPIError, requests.Timeout, requests.ConnectionError)
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


def classify_requests_exception(exc: Exception, response=None) -> Exception:
    """
    Turn a low-level requests exception / HTTP response into either a
    PermanentAPIError or TemporaryAPIError, so callers can decide whether
    to keep retrying.
    """
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return TemporaryAPIError(str(exc))

    if response is not None:
        status = response.status_code
        if status in (408, 429) or status >= 500:
            return TemporaryAPIError(f"Upstream returned status {status}")
        if 400 <= status < 500:
            return PermanentAPIError(f"Upstream returned status {status}: {response.text[:300]}")

    return TemporaryAPIError(str(exc))
