"""Application configuration.

Values are read from the environment (via python-dotenv loading .env in
create_app). Everything has a sane local-dev default so `uv run flask run`
works out of the box on a clean clone.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'sprachweg.sqlite').as_posix()}"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Local IANA timezone used to compute "today" for logging/streaks. This is a
    # fallback; the same value is also stored in the `setting` table and can be
    # changed from Settings without restarting the app.
    TIMEZONE = os.environ.get("TIMEZONE", "Europe/Berlin")

    WTF_CSRF_TIME_LIMIT = None  # sessions can sit open a long time; don't expire tokens


class DevConfig(Config):
    DEBUG = True


class ProdConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


def get_config(name: str | None) -> type[Config]:
    mapping = {"development": DevConfig, "production": ProdConfig, "testing": TestConfig}
    return mapping.get((name or "development").lower(), DevConfig)
