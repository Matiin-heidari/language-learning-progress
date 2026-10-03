from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from sprachweg.extensions import db
from sprachweg.models import (
    Language,
    Level,
    PlanItem,
    PlanItemStatus,
    StudyPlan,
    StudySession,
    today_local,
)
from sprachweg.services.context import get_current_language, set_current_language
from sprachweg.services.heatmap import build_heatmap
from sprachweg.services.language_catalog import list_available_templates_for
from sprachweg.services.milestones import check_milestones
from sprachweg.services.plans import ensure_plan_items
from sprachweg.services.progress import compute_eta, compute_overall_progress, mark_level_complete
from sprachweg.services.streaks import compute_plan_adherence, compute_streaks

bp = Blueprint("dashboard", __name__)


@bp.before_request
@login_required
def _require_login():
    pass


@bp.route("/dashboard")
def index():
    language = get_current_language()
    if language is None:
        available_templates = list_available_templates_for(current_user)
        return render_template("onboarding.html", available_templates=available_templates)

    progress = compute_overall_progress(language)
    eta = compute_eta(language, progress)
    streaks = compute_streaks(
        current_user.id, language.id, threshold=current_user.streak_min_minutes
    )
    adherence = compute_plan_adherence(language.id, days=7)

    today = today_local()
    active_plan = StudyPlan.query.filter_by(language_id=language.id, is_active=True).first()
    today_items = []
    if active_plan:
        ensure_plan_items(active_plan, start=today, end=today)
        today_items = (
            PlanItem.query.filter_by(plan_id=active_plan.id, date=today).order_by(PlanItem.id).all()
        )

    heatmap = build_heatmap(
        current_user.id, language.id, days=365, week_start=current_user.week_start
    )

    recent_sessions = (
        StudySession.query.filter_by(language_id=language.id)
        .order_by(StudySession.study_date.desc(), StudySession.id.desc())
        .limit(5)
        .all()
    )

    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    # Backfill ("mark level complete") catch-up entries are excluded here too --
    # otherwise one lump entry would make "this week" look enormous and every
    # other week look tiny by comparison.
    this_week_minutes = (
        db.session.query(db.func.coalesce(db.func.sum(StudySession.minutes), 0))
        .filter(
            StudySession.language_id == language.id,
            StudySession.study_date >= week_start,
            StudySession.study_date <= today,
            StudySession.is_backfill.is_(False),
        )
        .scalar()
    )
    last_week_minutes = (
        db.session.query(db.func.coalesce(db.func.sum(StudySession.minutes), 0))
        .filter(
            StudySession.language_id == language.id,
            StudySession.study_date >= last_week_start,
            StudySession.study_date < week_start,
            StudySession.is_backfill.is_(False),
        )
        .scalar()
    )
    week_delta_pct = None
    if last_week_minutes > 0:
        week_delta_pct = round((this_week_minutes - last_week_minutes) / last_week_minutes * 100)

    languages = (
        Language.query.filter_by(user_id=current_user.id, is_active=True)
        .order_by(Language.id.asc())
        .all()
    )

    return render_template(
        "dashboard.html",
        language=language,
        languages=languages,
        progress=progress,
        eta=eta,
        streaks=streaks,
        adherence=adherence,
        active_plan=active_plan,
        today_items=today_items,
        heatmap=heatmap,
        recent_sessions=recent_sessions,
        this_week_minutes=this_week_minutes,
        week_delta_pct=week_delta_pct,
        today=today,
        PlanItemStatus=PlanItemStatus,
    )


@bp.route("/lang/<code>")
def switch_language(code: str):
    language = Language.query.filter_by(user_id=current_user.id, code=code).first()
    if language:
        set_current_language(code)
    return redirect(url_for("dashboard.index"))


@bp.route("/levels/<int:level_id>/mark-complete", methods=["POST"])
def mark_complete(level_id: int):
    """The "I passed A1" button: logs catch-up sessions for the shortfall
    instead of requiring the exact hours studied. See services/progress.py."""
    language = get_current_language()
    level = Level.query.filter_by(id=level_id, language_id=language.id).first_or_404()

    on = None
    raw_date = request.form.get("completed_on", "").strip()
    if raw_date:
        try:
            on = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            on = None
    if on and on > today_local():
        on = today_local()

    added = mark_level_complete(language, level, on=on)
    if added:
        check_milestones(language)

    return redirect(url_for("dashboard.index"))
