# ==========================================
# OM Automation V2
# core/logger.py
# ==========================================

import os
import logging
from datetime import datetime

from modules.om_automation.config import LOG_DIR


class Logger:

    def __init__(self):

        os.makedirs(LOG_DIR, exist_ok=True)

        self.log_file = os.path.join(
            LOG_DIR,
            f"OM_{datetime.now().strftime('%Y%m%d')}.log"
        )

        self.logger = logging.getLogger("OMAutomation")
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                "%d-%m-%Y %H:%M:%S"
            )

            file_handler = logging.FileHandler(
                self.log_file,
                encoding="utf-8"
            )

            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    # ----------------------------

    def info(self, message):
        print("[INFO]", message)
        self.logger.info(message)

    # ----------------------------

    def warning(self, message):
        print("[WARNING]", message)
        self.logger.warning(message)

    # ----------------------------

    def error(self, message):
        print("[ERROR]", message)
        self.logger.error(message)

    # ----------------------------

    def success(self, message):
        print("[SUCCESS]", message)
        self.logger.info(f"SUCCESS | {message}")

    # ----------------------------

    def debug(self, message):
        print("[DEBUG]", message)
        self.logger.debug(message)


logger = Logger()
