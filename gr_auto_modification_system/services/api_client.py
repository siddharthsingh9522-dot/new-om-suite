"""
Low-level HTTP client for the upstream "load.omone.in" utility-service API.

This module is the ONLY place that knows how to physically make a request
(auth headers/cookies, timeout, retry, rate limiting). Everything else in
the app calls through cn_service / party_service / modification_service,
never requests directly.
"""
import logging
import threading
import time

import requests

from config import settings
from utils.retry import (
    build_retry_decorator,
    classify_requests_exception,
    PermanentAPIError,
    TemporaryAPIError,
)

logger = logging.getLogger("gr_auto_mod.api_client")


class _RateLimiter:
    """Simple token-bucket-ish limiter shared across threads in bulk mode."""

    def __init__(self, per_second: float):
        self._lock = threading.Lock()
        self._min_interval = 1.0 / per_second if per_second > 0 else 0
        self._last_call = 0.0

    def wait(self):
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            sleep_for = self._min_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_call = time.monotonic()


_rate_limiter = _RateLimiter(settings.API_RATE_LIMIT_PER_SECOND)


def _build_auth_headers_and_cookies():
    """
    Build auth headers/cookies from environment configuration ONLY.
    Never hardcode a token or cookie value in source code.
    """
    headers = {"Accept": "application/json"}
    cookies = {}

    mode = (settings.API_AUTH_MODE or "none").lower()
    if mode == "bearer" and settings.API_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {settings.API_BEARER_TOKEN}"
    elif mode == "cookie" and settings.API_SESSION_COOKIE:
        # Expect "name=value" pairs separated by ';' in the env variable.
        for pair in settings.API_SESSION_COOKIE.split(";"):
            if "=" in pair:
                name, value = pair.split("=", 1)
                cookies[name.strip()] = value.strip()
    return headers, cookies


class ApiClient:
    """Thin wrapper around `requests` with retry/backoff and rate limiting."""

    def __init__(self):
        self.base_url = settings.API_BASE_URL.rstrip("/")
        self.timeout = settings.API_REQUEST_TIMEOUT_SECONDS

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        headers, cookies = _build_auth_headers_and_cookies()
        kwargs.setdefault("headers", {}).update(headers)
        kwargs.setdefault("cookies", {}).update(cookies)
        kwargs.setdefault("timeout", self.timeout)

        decorator = build_retry_decorator(
            settings.API_RETRY_COUNT, settings.API_RETRY_BACKOFF_BASE_SECONDS
        )

        @decorator
        def _do_call():
            _rate_limiter.wait()
            try:
                response = requests.request(method, url, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                raise TemporaryAPIError(str(exc)) from exc

            if response.status_code >= 400:
                raise classify_requests_exception(
                    Exception(f"HTTP {response.status_code}"), response=response
                )

            try:
                return response.json()
            except ValueError as exc:
                raise PermanentAPIError(f"Invalid JSON returned by upstream API: {exc}") from exc

        return _do_call()

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def send(self, method: str, path: str, json_payload: dict) -> dict:
        """Generic verb for the (currently unconfigured) save/modify API."""
        return self._request(method.upper(), path, json=json_payload)


api_client = ApiClient()
