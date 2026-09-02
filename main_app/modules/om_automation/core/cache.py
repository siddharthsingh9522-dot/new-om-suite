# ==========================================
# OM Automation V2
# core/cache.py
# ==========================================

import threading
import time


class MemoryCache:
    """
    Thread-safe in-memory cache.

    Used for:
        Customer API
        GST API
        CN API (optional)
    """

    def __init__(self):
        self.cache = {}
        self.timestamp = {}
        self.lock = threading.Lock()

    # ------------------------------

    def exists(self, key):
        with self.lock:
            return key in self.cache

    # ------------------------------

    def get(self, key):
        with self.lock:
            return self.cache.get(key)

    # ------------------------------

    def set(self, key, value):
        with self.lock:
            self.cache[key] = value
            self.timestamp[key] = time.time()

    # ------------------------------

    def remove(self, key):
        with self.lock:
            self.cache.pop(key, None)
            self.timestamp.pop(key, None)

    # ------------------------------

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.timestamp.clear()


# Shared caches for repeated lookups across a batch
# (many CN rows can share the same Party Code / GSTIN).
customer_cache = MemoryCache()
gst_cache = MemoryCache()
