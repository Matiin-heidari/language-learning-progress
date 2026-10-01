from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from sprachweg.extensions import db
from sprachweg.models import (
    ActivityType,
    Language,
    Level,
    MilestoneEvent,
    StudySession,
    today_local,
)
from sprachweg.services.context import get_current_language, list_activity_types

bp = Blueprint("settings", __name__)


@bp.before_request
@login_required
def _require_login():
    pass


def _owned_level_or_404(level_id: int) -> Level:
    return (
        Level.query.join(Language)
        .filter(Level.id == level_id, Language.user_id == current_user.id)
        .first_or_404()
    )


def _owned_language_or_404(language_id: int) -> Language:
    return Language.query.filter_by(id=language_id, user_id=current_user.id).first_or_404()


@bp.route("/settings")
def index():
    language = get_current_language()
    languages = Language.query.filter_by(user_id=current_user.id).order_by(Language.id.asc()).all()
    levels = Level.query.filter_by(language_id=language.id).order_by(Level.sort_order).all()
    activities = list_activity_types()

    return render_template(
        "settings.html",
        language=language,
        languages=languages,
        levels=levels,
        activities=activities,
    )


@bp.route("/settings/general", methods=["POST"])
def update_general():
    from zoneinfo import ZoneInfo

    tz = request.form.get("timezone", "").strip()
    if tz:
        try:
            ZoneInfo(tz)
            current_user.timezone = tz
        except Exception:
            pass  # invalid tz name: silently keep the previous value

    week_start = request.form.get("week_start")
    if week_start in ("mon", "sun"):
        current_user.week_start = week_start

    theme = request.form.get("theme")
    if theme in ("system", "light", "dark"):
        current_user.theme = theme

    streak_min = request.form.get("streak_min_minutes", type=int)
    if streak_min and 1 <= streak_min <= 240:
        current_user.streak_min_minutes = streak_min

    daily_goal = request.form.get("daily_goal_minutes", type=int)
    if daily_goal and 5 <= daily_goal <= 960:
        current_user.daily_goal_minutes = daily_goal

    display_name = request.form.get("display_name", "").strip()
    if display_name:
        current_user.display_name = display_name[:64]

    is_public = request.form.get("is_public") == "on"
    current_user.is_public = is_public

    db.session.commit()
    return redirect(url_for("settings.index"))


@bp.route("/settings/account/password", methods=["POST"])
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    error = None
    if not current_user.check_password(current_password):
        error = "Current password is incorrect."
    elif len(new_password) < 8:
        error = "New password must be at least 8 characters."
    elif new_password != confirm:
        error = "New passwords don't match."

    if error:
        from flask import flash

        flash(error, "error")
    else:
        current_user.set_password(new_password)
        db.session.commit()
        from flask import flash

        flash("Password updated.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/settings/levels/<int:level_id>", methods=["POST"])
def update_level(level_id: int):
    level = _owned_level_or_404(level_id)
    hours = request.form.get("target_hours", type=float)
    if hours and hours > 0:
        level.target_hours = hours
        db.session.commit()
    return redirect(url_for("settings.index"))


@bp.route("/settings/levels/<int:level_id>/exam-passed", methods=["POST"])
def mark_exam_passed(level_id: int):
    level = _owned_level_or_404(level_id)
    passed_on = request.form.get("date")
    try:
        achieved = datetime.strptime(passed_on, "%Y-%m-%d").date() if passed_on else today_local()
    except ValueError:
        achieved = today_local()
    db.session.add(
        MilestoneEvent(
            language_id=level.language_id,
            kind="exam_passed",
            ref=level.code,
            achieved_on=achieved,
            seen=True,
        )
    )
    db.session.commit()
    return redirect(url_for("settings.index"))


@bp.route("/settings/languages", methods=["POST"])
def add_language():
    code = request.form.get("code", "").strip().lower()
    name = request.form.get("name", "").strip()
    native_name = request.form.get("native_name", "").strip() or name
    flag = request.form.get("flag_emoji", "").strip() or "🏳"
    exists = Language.query.filter_by(user_id=current_user.id, code=code).first()
    if code and name and not exists:
        db.session.add(
            Language(
                user_id=current_user.id,
                code=code,
                name=name,
                native_name=native_name,
                flag_emoji=flag,
            )
        )
        db.session.commit()
    return redirect(url_for("settings.index"))


@bp.route("/settings/languages/<int:language_id>/archive", methods=["POST"])
def archive_language(language_id: int):
    language = _owned_language_or_404(language_id)
    language.is_active = False
    db.session.commit()
    return redirect(url_for("settings.index"))


@bp.route("/settings/languages/<int:language_id>/goal", methods=["POST"])
def set_goal_level(language_id: int):
    language = _owned_language_or_404(language_id)
    level_id = request.form.get("goal_level_id", type=int)
    if level_id and Level.query.filter_by(id=level_id, language_id=language.id).first():
        language.goal_level_id = level_id
        db.session.commit()
    return redirect(url_for("settings.index"))


@bp.route("/settings/activities", methods=["POST"])
def add_activity():
    key = request.form.get("key", "").strip().lower()
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "").strip() or "book"
    already_taken = any(a.key == key for a in list_activity_types())
    if key and name and not already_taken:
        max_slot = db.session.query(db.func.max(ActivityType.color_slot)).scalar() or 0
        db.session.add(
            ActivityType(
                user_id=current_user.id,
                key=key,
                name=name,
                icon=icon,
                color_slot=min(8, max_slot + 1) if max_slot < 8 else ((max_slot % 8) + 1),
                sort_order=len(list_activity_types()),
            )
        )
        db.session.commit()
    return redirect(url_for("settings.index"))


@bp.route("/settings/activities/<int:activity_id>/archive", methods=["POST"])
def archive_activity(activity_id: int):
    # Only a user's own custom activity types can be archived -- a global
    # default (user_id IS NULL) is shared by everyone and stays put.
    activity = ActivityType.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    activity.is_archived = True
    db.session.commit()
    return redirect(url_for("settings.index"))


# --- Export / Import (current user's own data only) ---------------------


def build_export_payload(user=None) -> dict:
    user = user or current_user._get_current_object()
    return {
        "exported_at": datetime.utcnow().isoformat(),
        "username": user.username,
        "languages": [
            {
                "code": lang.code,
                "name": lang.name,
                "native_name": lang.native_name,
                "flag_emoji": lang.flag_emoji,
                "goal_level_code": lang.goal_level.code if lang.goal_level else None,
                "is_active": lang.is_active,
                "levels": [
                    {
                        "code": lv.code,
                        "name": lv.name,
                        "sort_order": lv.sort_order,
                        "target_hours": float(lv.target_hours),
                        "is_hidden": lv.is_hidden,
                    }
                    for lv in lang.levels
                ],
            }
            for lang in Language.query.filter_by(user_id=user.id).all()
        ],
        "activity_types": [
            {
                "key": a.key,
                "name": a.name,
                "icon": a.icon,
                "color_slot": a.color_slot,
                "sort_order": a.sort_order,
                "is_archived": a.is_archived,
            }
            for a in list_activity_types(user_id=user.id)
            if a.user_id == user.id
        ],
        "sessions": [
            {
                "language_code": s.language.code,
                "activity_key": s.activity_type.key,
                "study_date": s.study_date.isoformat(),
                "minutes": s.minutes,
                "note": s.note,
                "resource": s.resource,
                "is_backfill": s.is_backfill,
            }
            for s in StudySession.query.filter_by(user_id=user.id)
            .order_by(StudySession.study_date)
            .all()
        ],
    }


def restore_export_payload(payload: dict, user=None) -> None:
    """Additive import into `user`'s account (defaults to the current
    logged-in user): creates missing languages/levels/custom-activity-types,
    and adds sessions that don't already exist (matched on
    language+activity+date+minutes) to avoid duplicate-importing the same
    backup twice.
    """
    user = user or current_user._get_current_object()

    for lang_data in payload.get("languages", []):
        language = Language.query.filter_by(user_id=user.id, code=lang_data["code"]).first()
        if language is None:
            language = Language(
                user_id=user.id,
                code=lang_data["code"],
                name=lang_data["name"],
                native_name=lang_data.get("native_name", lang_data["name"]),
                flag_emoji=lang_data.get("flag_emoji", "🏳"),
                is_active=lang_data.get("is_active", True),
            )
            db.session.add(language)
            db.session.flush()
        for lv_data in lang_data.get("levels", []):
            level = Level.query.filter_by(language_id=language.id, code=lv_data["code"]).first()
            if level is None:
                level = Level(
                    language_id=language.id,
                    code=lv_data["code"],
                    name=lv_data["name"],
                    sort_order=lv_data["sort_order"],
                    target_hours=lv_data["target_hours"],
                    is_hidden=lv_data.get("is_hidden", False),
                )
                db.session.add(level)
        db.session.flush()
        goal_code = lang_data.get("goal_level_code")
        if goal_code:
            goal_level = Level.query.filter_by(language_id=language.id, code=goal_code).first()
            if goal_level:
                language.goal_level_id = goal_level.id

    for act_data in payload.get("activity_types", []):
        exists = any(a.key == act_data["key"] for a in list_activity_types(user_id=user.id))
        if not exists:
            db.session.add(
                ActivityType(
                    user_id=user.id,
                    key=act_data["key"],
                    name=act_data["name"],
                    icon=act_data.get("icon", "book"),
                    color_slot=act_data.get("color_slot", 1),
                    sort_order=act_data.get("sort_order", 0),
                    is_archived=act_data.get("is_archived", False),
                )
            )
    db.session.flush()

    lang_by_code = {lang.code: lang for lang in Language.query.filter_by(user_id=user.id).all()}
    act_by_key = {a.key: a for a in list_activity_types(user_id=user.id)}

    existing_keys = {
        (s.language_id, s.activity_type_id, s.study_date, s.minutes)
        for s in StudySession.query.filter_by(user_id=user.id).all()
    }
    for s_data in payload.get("sessions", []):
        language = lang_by_code.get(s_data["language_code"])
        activity = act_by_key.get(s_data["activity_key"])
        if not language or not activity:
            continue
        study_date = date.fromisoformat(s_data["study_date"])
        key = (language.id, activity.id, study_date, s_data["minutes"])
        if key in existing_keys:
            continue
        db.session.add(
            StudySession(
                user_id=user.id,
                language_id=language.id,
                activity_type_id=activity.id,
                study_date=study_date,
                minutes=s_data["minutes"],
                note=s_data.get("note"),
                resource=s_data.get("resource"),
                is_backfill=s_data.get("is_backfill", False),
            )
        )
        existing_keys.add(key)

    db.session.commit()


@bp.route("/export.json")
def export_json():
    payload = build_export_payload()
    return Response(
        jsonify(payload).get_data(),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=sprachweg-backup.json"},
    )


@bp.route("/settings/import", methods=["POST"])
def import_json():
    file = request.files.get("file")
    if file:
        import json

        payload = json.load(file.stream)
        restore_export_payload(payload)
    return redirect(url_for("settings.index"))
