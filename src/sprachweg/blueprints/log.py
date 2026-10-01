from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime

from flask import Blueprint, Response, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from sprachweg.extensions import db
from sprachweg.models import StudySession, today_local
from sprachweg.services.context import get_current_language, list_activity_types
from sprachweg.services.milestones import check_milestones

bp = Blueprint("log", __name__)


@bp.before_request
@login_required
def _require_login():
    pass


def _parse_minutes(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if ":" in raw:
        try:
            h, m = raw.split(":")
            return int(h) * 60 + int(m)
        except ValueError:
            return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@bp.route("/log")
def index():
    language = get_current_language()
    activity_filter = request.args.get("activity", type=int)
    date_from = _parse_date(request.args.get("from", ""))
    date_to = _parse_date(request.args.get("to", ""))

    query = StudySession.query.filter_by(language_id=language.id)
    if activity_filter:
        query = query.filter_by(activity_type_id=activity_filter)
    if date_from:
        query = query.filter(StudySession.study_date >= date_from)
    if date_to:
        query = query.filter(StudySession.study_date <= date_to)

    sessions = (
        query.order_by(StudySession.study_date.desc(), StudySession.id.desc()).limit(500).all()
    )

    grouped: dict[date, list[StudySession]] = {}
    for s in sessions:
        grouped.setdefault(s.study_date, []).append(s)

    return render_template(
        "log/index.html",
        language=language,
        grouped=grouped,
        activities=list_activity_types(),
        activity_filter=activity_filter,
        date_from=date_from,
        date_to=date_to,
        today=today_local(),
    )


@bp.route("/sessions/new", methods=["GET", "POST"])
def new_session():
    language = get_current_language()
    activities = list_activity_types()

    if request.method == "POST":
        study_date = _parse_date(request.form.get("study_date", "")) or today_local()
        if study_date > today_local():
            study_date = today_local()
        minutes = _parse_minutes(request.form.get("minutes", "")) or 0
        minutes = max(1, min(960, minutes))
        activity_id = request.form.get("activity_type_id", type=int)
        note = request.form.get("note", "").strip() or None
        resource = request.form.get("resource", "").strip() or None

        if activity_id:
            session = StudySession(
                user_id=current_user.id,
                language_id=language.id,
                activity_type_id=activity_id,
                study_date=study_date,
                minutes=minutes,
                note=note,
                resource=resource,
            )
            db.session.add(session)
            db.session.commit()
            new_milestones = check_milestones(language)

            if request.headers.get("HX-Request"):
                activity_name = session.activity_type.name
                trigger_payload = {
                    "sessionLogged": {
                        "message": f"+{minutes} min {activity_name} logged",
                        "milestones": [m.label for m in new_milestones],
                    }
                }
                response = Response("")  # empty body closes the modal (#modal-root target)
                response.headers["HX-Trigger"] = json.dumps(trigger_payload)
                return response
            return redirect(url_for("dashboard.index"))

    if request.headers.get("HX-Request"):
        return render_template(
            "partials/quick_log.html", activities=activities, today=today_local()
        )
    return render_template(
        "log/form.html", activities=activities, session=None, today=today_local()
    )


@bp.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
def edit_session(session_id: int):
    language = get_current_language()
    session_obj = StudySession.query.filter_by(
        id=session_id, language_id=language.id
    ).first_or_404()
    activities = list_activity_types()

    if request.method == "POST":
        study_date = _parse_date(request.form.get("study_date", "")) or session_obj.study_date
        minutes = _parse_minutes(request.form.get("minutes", "")) or session_obj.minutes
        session_obj.study_date = min(study_date, today_local())
        session_obj.minutes = max(1, min(960, minutes))
        session_obj.activity_type_id = request.form.get(
            "activity_type_id", type=int, default=session_obj.activity_type_id
        )
        session_obj.note = request.form.get("note", "").strip() or None
        session_obj.resource = request.form.get("resource", "").strip() or None
        db.session.commit()
        return redirect(url_for("log.index"))

    return render_template(
        "log/form.html", activities=activities, session=session_obj, today=today_local()
    )


@bp.route("/sessions/<int:session_id>/delete", methods=["POST"])
def delete_session(session_id: int):
    language = get_current_language()
    session_obj = StudySession.query.filter_by(
        id=session_id, language_id=language.id
    ).first_or_404()
    db.session.delete(session_obj)
    db.session.commit()
    if request.headers.get("HX-Request"):
        return ""
    return redirect(url_for("log.index"))


@bp.route("/day/<date_str>")
def day_drawer(date_str: str):
    language = get_current_language()
    day = _parse_date(date_str)
    if day is None:
        return "", 404
    sessions = (
        StudySession.query.filter_by(language_id=language.id, study_date=day)
        .order_by(StudySession.id)
        .all()
    )
    total = sum(s.minutes for s in sessions)
    return render_template("partials/day_drawer.html", day=day, sessions=sessions, total=total)


@bp.route("/export.csv")
def export_csv():
    language = get_current_language()
    sessions = (
        StudySession.query.filter_by(language_id=language.id)
        .order_by(StudySession.study_date.asc())
        .all()
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "activity", "minutes", "resource", "note"])
    for s in sessions:
        writer.writerow(
            [
                s.study_date.isoformat(),
                s.activity_type.name,
                s.minutes,
                s.resource or "",
                s.note or "",
            ]
        )
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={language.code}-sessions.csv"},
    )
