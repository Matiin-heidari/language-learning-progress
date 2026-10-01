from __future__ import annotations

import pytest

from sprachweg import create_app
from sprachweg.extensions import db as _db
from sprachweg.models import User
from sprachweg.seed import seed_global_activity_types, seed_user_language

TEST_PASSWORD = "correct horse battery staple"  # noqa: S105 (test fixture only)


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def user(app, db):
    """A test account. Global activity types are seeded alongside it since
    almost everything (sessions, plans) needs at least one to exist.
    """
    seed_global_activity_types()
    u = User(username="testuser", display_name="Test User", email="test@example.com")
    u.set_password(TEST_PASSWORD)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def language(app, db, user):
    """Seed German + CEFR levels + skill mix for `user` and return the Language row."""
    return seed_user_language(user)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(client, user):
    """A test client already logged in as `user`."""
    client.post("/login", data={"username": user.username, "password": TEST_PASSWORD})
    return client
