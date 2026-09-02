# ==========================================
# OM Automation V2
# api/session.py
# ==========================================

import requests

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from modules.om_automation.config import TIMEOUT
from modules.om_automation.config import RETRY_COUNT
from modules.om_automation.config import HEADERS


class HTTPSession:

    def __init__(self):

        retry = Retry(
            total=RETRY_COUNT,
            connect=RETRY_COUNT,
            read=RETRY_COUNT,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )

        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=50,
            pool_maxsize=50
        )

        self.session = requests.Session()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(HEADERS)

    def get(self, url, **kwargs):
        timeout = kwargs.pop("timeout", TIMEOUT)
        return self.session.get(url, timeout=timeout, **kwargs)

    def post(self, url, **kwargs):
        timeout = kwargs.pop("timeout", TIMEOUT)
        return self.session.post(url, timeout=timeout, **kwargs)


http = HTTPSession()
