"""Weekly plan template -> daily plan item expansion. See PLAN.md §6.5.

Key rules:
- Never generate items before the plan's `starts_on`.
- Never generate more than 7 days into the future (nothing to check off yet).
- Editing a template item only ever touches *future* `pending` items —
  history is never rewritten.
- Marking an item done/partial creates or updates exactly one linked
  StudySession; un-marking (back to pending) deletes that session.
"""

from __future__ import annotations

from datetime import date, timedelta

from sprachweg.extensions import db
from sprachweg.models import (
    PlanItem,
    PlanItemStatus,
    PlanTemplateItem,
    StudyPlan,
    StudySession,
    today_local,
)

MAX_FUTURE_DAYS = 7


def ensure_plan_items(plan: StudyPlan, *, start: date, end: date) -> None:
    """Lazily materialise PlanItem rows for [start, end] from the plan's
    template. Idempotent: relies on the (template_item_id, date) unique
    constraint and `INSERT ... ON CONFLICT DO NOTHING` semantics via a
    pre-check set, so calling this repeatedly is cheap and safe.
    """
    today = today_local()
    horizon = today + timedelta(days=MAX_FUTURE_DAYS)
    effective_start = max(start, plan.starts_on)
    effective_end = min(end, plan.ends_on) if plan.ends_on else end
    effective_end = min(effective_end, horizon)
    if effective_start > effective_end:
        return

    existing = {
        (pi.template_item_id, pi.date)
        for pi in PlanItem.query.filter(
            PlanItem.plan_id == plan.id,
            PlanItem.date >= effective_start,
            PlanItem.date <= effective_end,
            PlanItem.template_item_id.isnot(None),
        ).all()
    }

    templates_by_weekday: dict[int, list[PlanTemplateItem]] = {}
    for t in plan.template_items:
        templates_by_weekday.setdefault(t.weekday, []).append(t)

    cursor = effective_start
    new_items = []
    while cursor <= effective_end:
        for template in templates_by_weekday.get(cursor.weekday(), []):
            key = (template.id, cursor)
            if key not in existing:
                new_items.append(
                    PlanItem(
                        plan_id=plan.id,
                        template_item_id=template.id,
                        date=cursor,
                        activity_type_id=template.activity_type_id,
                        planned_minutes=template.planned_minutes,
                        title=template.title,
                        status=PlanItemStatus.PENDING,
                    )
                )
        cursor += timedelta(days=1)

    if new_items:
        db.session.add_all(new_items)
        db.session.commit()


def regenerate_future_for_template(template: PlanTemplateItem) -> None:
    """Call after editing/deleting a template item: wipe *future* pending
    items tied to it so the next `ensure_plan_items` call regenerates them
    with the new minutes/title. Past and non-pending items are left alone.
    """
    today = today_local()
    PlanItem.query.filter(
        PlanItem.template_item_id == template.id,
        PlanItem.date >= today,
        PlanItem.status == PlanItemStatus.PENDING,
    ).delete(synchronize_session=False)
    db.session.commit()


def set_item_status(
    item: PlanItem, status: PlanItemStatus, *, actual_minutes: int | None = None
) -> None:
    """Transition a plan item and keep its linked StudySession in sync.

    done    -> creates/updates a session for `actual_minutes or planned_minutes`
    partial -> creates/updates a session for `actual_minutes` (required)
    skipped -> deletes any linked session, no session created
    pending -> (un-checking) deletes any linked session
    """
    if status in (PlanItemStatus.DONE, PlanItemStatus.PARTIAL):
        minutes = actual_minutes if actual_minutes is not None else item.planned_minutes
        minutes = max(1, min(960, minutes))
        if item.session is not None:
            item.session.minutes = minutes
        else:
            session = StudySession(
                user_id=item.plan.language.user_id,
                language_id=item.plan.language_id,
                activity_type_id=item.activity_type_id,
                study_date=item.date,
                minutes=minutes,
                resource=item.title,
                plan_item_id=item.id,
            )
            db.session.add(session)
    else:
        if item.session is not None:
            db.session.delete(item.session)

    item.status = status
    db.session.commit()


def suggest_template(level, *, minutes_per_day: int, days_per_week: int) -> list[dict]:
    """Build a suggested (unsaved) weekly template from a level's skill mix
    (PLAN.md §2.4): split `minutes_per_day` across activities by the level's
    percentages, rounded to 5-minute blocks, repeated on the chosen number of
    days starting Monday. Returns plain dicts for the builder UI to
    render/edit before saving.
    """
    days_per_week = max(1, min(7, days_per_week))
    weekdays = list(range(days_per_week))  # Mon, Tue, ... up to N days

    suggestions = []
    for st in sorted(level.skill_targets, key=lambda s: -float(s.percent)):
        per_day = round(minutes_per_day * float(st.percent) / 100)
        per_day = max(5, round(per_day / 5) * 5)  # round to nearest 5 min
        for wd in weekdays:
            suggestions.append(
                {
                    "weekday": wd,
                    "activity_type_id": st.activity_type_id,
                    "activity_name": st.activity_type.name,
                    "planned_minutes": per_day,
                }
            )
    return suggestions


def activate_plan(plan: StudyPlan) -> None:
    """Reactivate an archived plan (un-archive). Deactivates whatever plan is
    currently active for the same language first, since only one plan can be
    active per language. The plan's original `starts_on` is left untouched;
    `ends_on` is cleared since it's ongoing again.
    """
    StudyPlan.query.filter(
        StudyPlan.language_id == plan.language_id,
        StudyPlan.is_active.is_(True),
        StudyPlan.id != plan.id,
    ).update({"is_active": False, "ends_on": today_local()})
    plan.is_active = True
    plan.ends_on = None
    db.session.commit()


def delete_plan(plan: StudyPlan) -> None:
    """Permanently delete a plan and its template/daily items. Any
    StudySession a plan item had created stays -- it's unlinked (set back to
    an ordinary ad-hoc session) rather than deleted, so real logged time is
    never lost just because its plan was removed.
    """
    linked_sessions = StudySession.query.filter(
        StudySession.plan_item_id.in_(db.session.query(PlanItem.id).filter_by(plan_id=plan.id))
    ).all()
    for session in linked_sessions:
        session.plan_item_id = None
    db.session.delete(plan)  # cascades to template_items and items
    db.session.commit()
