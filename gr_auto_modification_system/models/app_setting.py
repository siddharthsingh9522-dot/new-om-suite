"""
AppSetting model: a simple key/value store for runtime-adjustable,
non-sensitive settings shown on the Settings page (timeouts, retry
counts, concurrency, etc.). Secrets are NEVER stored here - they stay
in environment variables only.
"""
from datetime import datetime

from models.database import db


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        row = AppSetting.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = AppSetting.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
        else:
            row = AppSetting(key=key, value=str(value))
            db.session.add(row)
        db.session.commit()
        return row
