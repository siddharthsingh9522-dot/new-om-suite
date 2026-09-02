"""
SQLAlchemy database instance, shared across the application.

Includes a lightweight, best-effort auto-migration step: this project uses
db.create_all() rather than a full migration framework (Alembic), so when a
new column is added to a model, an EXISTING sqlite database file on disk
would otherwise be missing that column and raise "no such column" errors.
On startup we compare each model's columns against what's actually in the
database and ALTER TABLE ADD COLUMN for anything missing. This preserves
existing batch/audit history across upgrades instead of requiring a wipe.

For a production Postgres deployment, replace this with real Alembic
migrations - this auto-migration is intentionally conservative (nullable
column additions only) and is not a substitute for one.
"""
import logging

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

db = SQLAlchemy()
logger = logging.getLogger("gr_auto_mod.database")


def _auto_migrate(app):
    """Best-effort: add any model columns missing from the live database."""
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        for table in db.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table - create_all() already handled it

            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                try:
                    col_type = column.type.compile(dialect=db.engine.dialect)
                    ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                    with db.engine.begin() as conn:
                        conn.execute(text(ddl))
                    logger.info("Auto-migration: added column %s.%s", table.name, column.name)
                except Exception:  # noqa: BLE001 - never block startup over a migration hiccup
                    logger.exception("Auto-migration failed for %s.%s", table.name, column.name)


def init_db(app):
    # SQLite: raise the busy-timeout so concurrent writes from bulk
    # processing threads queue briefly instead of immediately raising
    # "database is locked".
    if app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
        app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {})
        app.config["SQLALCHEMY_ENGINE_OPTIONS"].setdefault("connect_args", {"timeout": 30})

    db.init_app(app)
    with app.app_context():
        # Import models so they are registered on the metadata before create_all
        from models.batch import Batch          # noqa: F401
        from models.batch_item import BatchItem  # noqa: F401
        from models.audit_log import AuditLog    # noqa: F401
        from models.app_setting import AppSetting  # noqa: F401
        from models.module_batch import ModuleBatch          # noqa: F401
        from models.module_batch_item import ModuleBatchItem  # noqa: F401
        db.create_all()

    _auto_migrate(app)
