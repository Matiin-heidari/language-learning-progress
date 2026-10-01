"""Small shared helpers used by multiple blueprints. All assume a logged-in
user (every protected blueprint enforces this), so they read `current_user`
directly rather than taking it as a parameter everywhere.
"""

from __future__ import annotations

from flask import session
from flask_login import current_user
from sqlalchemy import or_

from sprachweg.models import ActivityType, Language


def list_activity_types(user_id: int | None = None) -> list[ActivityType]:
    """The global default activity types plus the given user's own custom
    ones, active (non-archived), in their fixed display order. Defaults to
    the current logged-in user; a few CLI commands run outside a request
    context and pass `user_id` explicitly instead.
    """
    if user_id is None:
        user_id = current_user.id
    return (
        ActivityType.query.filter(
            or_(ActivityType.user_id.is_(None), ActivityType.user_id == user_id)
        )
        .filter_by(is_archived=False)
        .order_by(ActivityType.sort_order)
        .all()
    )


def get_current_language() -> Language | None:
    """The current user's language currently selected in the UI (sticky via
    session cookie, falling back to their first active language). Returns
    None only if the user has no active language at all.
    """
    code = session.get("language_code")
    language = None
    if code:
        language = Language.query.filter_by(
            user_id=current_user.id, code=code, is_active=True
        ).first()
    if language is None:
        language = (
            Language.query.filter_by(user_id=current_user.id, is_active=True)
            .order_by(Language.id.asc())
            .first()
        )
    return language


def set_current_language(code: str) -> None:
    session["language_code"] = code
