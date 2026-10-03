"""Admin-only area: manage the shared language catalog (which languages
exist, with what per-CEFR-level hour targets), see/adjust each account's
streak threshold, and download a full database backup. None of this grants
access to other accounts' personal data (sessions, plans, notes) -- it's
catalog/ops management, not a support back-door.
"""

from __future__ import annotations

import os

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from sprachweg.extensions import db
from sprachweg.models import User
from sprachweg.services.backup import NotSqliteError, create_db_backup
from sprachweg.services.language_catalog import (
    LEVEL_CODES,
    create_language_template,
    list_language_templates,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
@login_required
def _require_admin():
    if not current_user.is_admin:
        abort(403)


@bp.route("/")
def index():
    users = User.query.order_by(User.id).all()
    templates = list_language_templates()
    return render_template("admin/index.html", users=users, templates=templates)


@bp.route("/users/<int:user_id>/streak-threshold", methods=["POST"])
def update_streak_threshold(user_id: int):
    user = User.query.filter_by(id=user_id).first_or_404()
    minutes = request.form.get("streak_min_minutes", type=int)
    if minutes and 1 <= minutes <= 240:
        user.streak_min_minutes = minutes
        db.session.commit()
    return redirect(url_for("admin.index"))


@bp.route("/languages/new", methods=["GET", "POST"])
def new_language():
    error = None
    if request.method == "POST":
        code = request.form.get("code", "").strip().lower()
        name = request.form.get("name", "").strip()
        native_name = request.form.get("native_name", "").strip() or name
        flag_emoji = request.form.get("flag_emoji", "").strip() or "🏳"
        goal_level_code = request.form.get("goal_level_code", "C1")

        level_hours: dict[str, float] = {}
        for code_lvl in LEVEL_CODES:
            raw = request.form.get(f"hours_{code_lvl}", "").strip()
            if raw:
                try:
                    hours = float(raw)
                    if hours > 0:
                        level_hours[code_lvl] = hours
                except ValueError:
                    pass

        existing = any(t.code == code for t in list_language_templates())
        if not code or not name:
            error = "Code and name are required."
        elif existing:
            error = f"A '{code}' template already exists in the catalog."
        elif not level_hours:
            error = "Set at least one level's hour target."
        else:
            create_language_template(
                code=code,
                name=name,
                native_name=native_name,
                flag_emoji=flag_emoji,
                level_hours=level_hours,
                goal_level_code=goal_level_code if goal_level_code in level_hours else None,
            )
            return redirect(url_for("admin.index"))

    return render_template("admin/new_language.html", error=error, level_codes=LEVEL_CODES)


@bp.route("/backup")
def backup():
    try:
        path = create_db_backup()
    except NotSqliteError:
        abort(400, "DATABASE_URL isn't SQLite -- back this up with your DB's own tool instead.")
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))
