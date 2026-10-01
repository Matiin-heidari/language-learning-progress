from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from sprachweg.extensions import db
from sprachweg.models import (
    Language,
    PlanItem,
    PlanItemStatus,
    PlanTemplateItem,
    StudyPlan,
    StudySession,
    today_local,
)
from sprachweg.services.context import get_current_language, list_activity_types
from sprachweg.services.milestones import check_milestones
from sprachweg.services.plans import (
    activate_plan,
    delete_plan,
    ensure_plan_items,
    regenerate_future_for_template,
    set_item_status,
    suggest_template,
)

bp = Blueprint("plan", __name__)

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@bp.before_request
@login_required
def _require_login():
    pass


def _owned_plan_or_404(plan_id: int) -> StudyPlan:
    """A plan belonging to the current user, or 404 -- guards every plan
    mutation route from acting on someone else's plan by id-guessing."""
    return (
        StudyPlan.query.join(Language)
        .filter(StudyPlan.id == plan_id, Language.user_id == current_user.id)
        .first_or_404()
    )


def _owned_template_item_or_404(item_id: int) -> PlanTemplateItem:
    return (
        PlanTemplateItem.query.join(StudyPlan)
        .join(Language)
        .filter(PlanTemplateItem.id == item_id, Language.user_id == current_user.id)
        .first_or_404()
    )


def _owned_plan_item_or_404(item_id: int) -> PlanItem:
    return (
        PlanItem.query.join(StudyPlan)
        .join(Language)
        .filter(PlanItem.id == item_id, Language.user_id == current_user.id)
        .first_or_404()
    )


@bp.route("/plan")
def index():
    language = get_current_language()
    active_plan = StudyPlan.query.filter_by(language_id=language.id, is_active=True).first()
    archived_plans = (
        StudyPlan.query.filter_by(language_id=language.id, is_active=False)
        .order_by(StudyPlan.starts_on.desc())
        .all()
    )
    activities = list_activity_types()

    items_by_day: dict[int, list[PlanTemplateItem]] = {i: [] for i in range(7)}
    day_totals = {i: 0 for i in range(7)}
    if active_plan:
        for item in active_plan.template_items:
            items_by_day[item.weekday].append(item)
            day_totals[item.weekday] += item.planned_minutes

    return render_template(
        "plan/index.html",
        language=language,
        active_plan=active_plan,
        archived_plans=archived_plans,
        activities=activities,
        items_by_day=items_by_day,
        day_totals=day_totals,
        weekday_names=WEEKDAY_NAMES,
    )


@bp.route("/plan", methods=["POST"])
def create_plan():
    language = get_current_language()
    StudyPlan.query.filter_by(language_id=language.id, is_active=True).update({"is_active": False})
    plan = StudyPlan(
        language_id=language.id,
        name=request.form.get("name", "My plan").strip() or "My plan",
        starts_on=today_local(),
        is_active=True,
    )
    db.session.add(plan)
    db.session.commit()
    return redirect(url_for("plan.index"))


@bp.route("/plan/<int:plan_id>/items", methods=["POST"])
def add_template_item(plan_id: int):
    plan = _owned_plan_or_404(plan_id)
    weekday = request.form.get("weekday", type=int)
    activity_type_id = request.form.get("activity_type_id", type=int)
    minutes = request.form.get("planned_minutes", type=int) or 30
    title = request.form.get("title", "").strip() or None
    if weekday is not None and activity_type_id:
        item = PlanTemplateItem(
            plan_id=plan.id,
            weekday=weekday,
            activity_type_id=activity_type_id,
            planned_minutes=max(5, min(600, minutes)),
            title=title,
            sort_order=len(plan.template_items),
        )
        db.session.add(item)
        db.session.commit()
    return redirect(url_for("plan.index"))


@bp.route("/plan/items/<int:item_id>/delete", methods=["POST"])
def delete_template_item(item_id: int):
    item = _owned_template_item_or_404(item_id)
    regenerate_future_for_template(item)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("plan.index"))


@bp.route("/plan/apply-to-days", methods=["POST"])
def apply_to_days():
    """ "Universal daily plan" mode: build one day's worth of activities and
    stamp it onto every chosen weekday at once, instead of repeating the same
    entries 7 times in the per-day grid. Adds to whatever's already on those
    days (same non-destructive behavior as the grid's own "+ Add"); creates
    the plan first if none is active yet.
    """
    language = get_current_language()
    plan = StudyPlan.query.filter_by(language_id=language.id, is_active=True).first()
    if plan is None:
        plan = StudyPlan(
            language_id=language.id, name="My plan", starts_on=today_local(), is_active=True
        )
        db.session.add(plan)
        db.session.flush()

    weekdays = sorted({int(w) for w in request.form.getlist("weekday") if w.isdigit()})
    activity_ids = request.form.getlist("activity_type_id[]")
    minutes_list = request.form.getlist("planned_minutes[]")

    next_sort_order = len(plan.template_items)
    added = False
    for wd in weekdays:
        if not (0 <= wd <= 6):
            continue
        for activity_id_raw, minutes_raw in zip(activity_ids, minutes_list, strict=False):
            if not activity_id_raw or not minutes_raw:
                continue
            try:
                activity_id = int(activity_id_raw)
                minutes = int(minutes_raw)
            except ValueError:
                continue
            db.session.add(
                PlanTemplateItem(
                    plan_id=plan.id,
                    weekday=wd,
                    activity_type_id=activity_id,
                    planned_minutes=max(5, min(600, minutes)),
                    sort_order=next_sort_order,
                )
            )
            next_sort_order += 1
            added = True

    if added:
        db.session.commit()
    return redirect(url_for("plan.index"))


@bp.route("/plan/suggest", methods=["POST"])
def suggest():
    language = get_current_language()
    from sprachweg.services.progress import compute_overall_progress

    progress = compute_overall_progress(language)
    current = progress.current_level
    if current is None:
        return redirect(url_for("plan.index"))

    minutes_per_day = request.form.get("minutes_per_day", type=int) or 90
    days_per_week = request.form.get("days_per_week", type=int) or 5

    suggestions = suggest_template(
        current.level, minutes_per_day=minutes_per_day, days_per_week=days_per_week
    )

    plan = StudyPlan.query.filter_by(language_id=language.id, is_active=True).first()
    if plan is None:
        plan = StudyPlan(
            language_id=language.id,
            name=f"{current.level.code} plan",
            starts_on=today_local(),
            is_active=True,
        )
        db.session.add(plan)
        db.session.flush()
    else:
        PlanTemplateItem.query.filter_by(plan_id=plan.id).delete()

    for order, s in enumerate(suggestions):
        db.session.add(
            PlanTemplateItem(
                plan_id=plan.id,
                weekday=s["weekday"],
                activity_type_id=s["activity_type_id"],
                planned_minutes=s["planned_minutes"],
                sort_order=order,
            )
        )
    db.session.commit()
    return redirect(url_for("plan.index"))


@bp.route("/plan/<int:plan_id>/archive", methods=["POST"])
def archive_plan(plan_id: int):
    plan = _owned_plan_or_404(plan_id)
    plan.is_active = False
    plan.ends_on = today_local()
    db.session.commit()
    return redirect(url_for("plan.index"))


@bp.route("/plan/<int:plan_id>/activate", methods=["POST"])
def activate_plan_route(plan_id: int):
    plan = _owned_plan_or_404(plan_id)
    activate_plan(plan)
    return redirect(url_for("plan.index"))


@bp.route("/plan/<int:plan_id>/delete", methods=["POST"])
def delete_plan_route(plan_id: int):
    plan = _owned_plan_or_404(plan_id)
    delete_plan(plan)
    return redirect(url_for("plan.index"))


@bp.route("/plan-items/<int:item_id>/status", methods=["POST"])
def update_status(item_id: int):
    item = _owned_plan_item_or_404(item_id)
    status_raw = request.form.get("status", "pending")
    try:
        status = PlanItemStatus(status_raw)
    except ValueError:
        status = PlanItemStatus.PENDING
    minutes = request.form.get("actual_minutes", type=int)
    set_item_status(item, status, actual_minutes=minutes)

    new_milestones = []
    if status in (PlanItemStatus.DONE, PlanItemStatus.PARTIAL):
        new_milestones = check_milestones(item.plan.language)

    if request.headers.get("HX-Request"):
        return render_template(
            "partials/plan_item.html",
            item=item,
            PlanItemStatus=PlanItemStatus,
            milestones=new_milestones,
        )
    return redirect(url_for("dashboard.index"))


@bp.route("/today")
def today_view():
    language = get_current_language()
    day = today_local()
    plan = StudyPlan.query.filter_by(language_id=language.id, is_active=True).first()
    items = []
    if plan:
        ensure_plan_items(plan, start=day, end=day + timedelta(days=1))
        items = PlanItem.query.filter_by(plan_id=plan.id, date=day).order_by(PlanItem.id).all()

    today_minutes = (
        db.session.query(db.func.coalesce(db.func.sum(StudySession.minutes), 0))
        .filter(StudySession.language_id == language.id, StudySession.study_date == day)
        .scalar()
    )
    daily_goal = current_user.daily_goal_minutes

    return render_template(
        "today.html",
        language=language,
        day=day,
        items=items,
        PlanItemStatus=PlanItemStatus,
        today_minutes=today_minutes,
        daily_goal=daily_goal,
    )
