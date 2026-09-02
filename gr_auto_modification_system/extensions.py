"""
Shared Flask extension instances.

Kept separate from app.py so other modules (routes/auth.py in particular)
can import `csrf` and call `csrf.protect()` explicitly on the traditional
HTML form posts (login/logout) without creating an import cycle with the
application factory.
"""
from flask_wtf import CSRFProtect

csrf = CSRFProtect()
