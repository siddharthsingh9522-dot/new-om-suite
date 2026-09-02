"""
GR AUTO MODIFICATION SYSTEM
Application entrypoint / factory.

Run locally:
    python app.py

Run with gunicorn:
    gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
"""
import logging
import os

from flask import Flask
from flask_wtf import CSRFProtect

from config import settings
from models import init_db
from utils.helpers import ensure_dirs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def create_app():
    app = Flask(__name__)
    app.config.from_object(settings)

    ensure_dirs(settings.UPLOAD_FOLDER, settings.EXPORT_FOLDER)

    init_db(app)

    if settings.WTF_CSRF_ENABLED:
        csrf = CSRFProtect(app)
        # JSON APIs called via fetch() send a header instead of a hidden
        # form field; exempt the JSON API blueprints from CSRF and rely on
        # SameSite cookies + same-origin fetch instead, while keeping CSRF
        # protection on any traditional HTML form posts.
        app.config["WTF_CSRF_CHECK_DEFAULT"] = False

    from routes.dashboard import dashboard_bp
    from routes.single_cn import single_cn_bp
    from routes.bulk import bulk_bp
    from routes.history import history_bp
    from routes.api import api_bp
    from routes.settings_routes import settings_bp
    from routes.auth import auth_bp
    from routes.modules import modules_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(single_cn_bp)
    app.register_blueprint(bulk_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(modules_bp)

    @app.context_processor
    def inject_globals():
        from config.modules_config import all_modules
        from services import auth_service
        return {
            "app_name": "GR Auto Modification System",
            "save_api_ready": settings.save_api_ready(),
            "new_modules": all_modules(),
            "current_auth_user": auth_service.current_user(),
        }

    @app.errorhandler(404)
    def not_found(e):
        return {"ok": False, "error": "Not found"}, 404

    @app.errorhandler(500)
    def server_error(e):
        logging.getLogger("gr_auto_mod").exception("Unhandled server error")
        return {"ok": False, "error": "Internal server error"}, 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=settings.DEBUG)
