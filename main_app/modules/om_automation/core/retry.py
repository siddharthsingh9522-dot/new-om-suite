# ==========================================
# OM Automation V2
# core/retry.py
# ==========================================

import time
import functools
import traceback


class Retry:
    """
    Decorator for retrying a function call with
    exponential backoff.

    Intended for wrapping higher-level API .fetch()
    methods that can fail 'softly' (e.g. bad JSON,
    unexpected payload shape) in ways the transport-level
    urllib3 Retry in api/session.py won't catch, since
    those failures often still come back as HTTP 200.
    """

    def __init__(
        self,
        retries=3,
        delay=2,
        backoff=2,
        exceptions=(Exception,)
    ):
        self.retries = retries
        self.delay = delay
        self.backoff = backoff
        self.exceptions = exceptions

    def __call__(self, func):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            retries = self.retries
            delay = self.delay
            last_exception = None

            while retries > 0:

                try:
                    return func(*args, **kwargs)

                except self.exceptions as e:

                    last_exception = e
                    retries -= 1

                    traceback.print_exc()

                    if retries <= 0:
                        raise

                    time.sleep(delay)
                    delay *= self.backoff

            # Should not normally be reached, but guards
            # against falling through silently.
            if last_exception is not None:
                raise last_exception

        return wrapper
