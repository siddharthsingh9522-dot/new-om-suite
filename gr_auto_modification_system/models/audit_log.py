"""
AuditLog model: append-only trail of significant actions taken in the
system (previews run, confirmations, executions, retries, exports).
"""
from datetime import datetime

from models.database import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(64), nullable=True, index=True)
    gr_number = db.Column(db.String(64), nullable=True, index=True)
    action = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text, nullable=True)
    actor = db.Column(db.String(120), default="system")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "gr_number": self.gr_number,
            "action": self.action,
            "details": self.details,
            "actor": self.actor,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
