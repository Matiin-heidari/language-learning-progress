from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask

from sprachweg.config import INSTANCE_DIR, get_config
from sprachweg.extensions import csrf, db, login_manager, migrate

load_dotenv()


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config(config_name or os.environ.get("FLASK_ENV")))

    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    _register_login_manager()
    _register_blueprints(app)
    _register_context_processors(app)

    from sprachweg.cli import register_cli

    register_cli(app)

    return app


def _register_login_manager() -> None:
    from sprachweg.models import User

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        return db.session.get(User, int(user_id))


def _register_blueprints(app: Flask) -> None:
    from sprachweg.blueprints.auth import bp as auth_bp
    from sprachweg.blueprints.dashboard import bp as dashboard_bp
    from sprachweg.blueprints.log import bp as log_bp
    from sprachweg.blueprints.main import bp as main_bp
    from sprachweg.blueprints.plan import bp as plan_bp
    from sprachweg.blueprints.profile import bp as profile_bp
    from sprachweg.blueprints.settings import bp as settings_bp
    from sprachweg.blueprints.stats import bp as stats_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(log_bp)
    app.register_blueprint(plan_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(profile_bp)


def _register_context_processors(app: Flask) -> None:
    from sprachweg.models import today_local

    @app.context_processor
    def inject_globals():
        try:
            today = today_local()
        except Exception:
            today = None
        return {"app_today": today}
