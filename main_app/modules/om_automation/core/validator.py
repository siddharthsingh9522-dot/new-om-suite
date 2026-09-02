# ==========================================
# OM Automation V2
# core/validator.py
# ==========================================

import re


class CNValidator:
    """
    Validate CN / LR / Docket / Billty Numbers
    """

    def __init__(self):
        self.allowed = re.compile(r"^[A-Za-z0-9\-/]+$")

    def clean(self, value):

        if value is None:
            return ""

        value = str(value).strip()
        value = value.replace("\n", "")
        value = value.replace("\t", "")

        return value

    def validate(self, value):

        value = self.clean(value)

        if value == "":
            return False, "Blank Value"

        if len(value) < 5:
            return False, "Too Short"

        if len(value) > 30:
            return False, "Too Long"

        if self.allowed.match(value) is None:
            return False, "Invalid Characters"

        return True, "Valid"

    def is_duplicate(self, value, cache):

        value = self.clean(value)

        if value in cache:
            return True

        cache.add(value)
        return False


validator = CNValidator()
