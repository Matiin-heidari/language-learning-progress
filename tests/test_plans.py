from __future__ import annotations

from datetime import date

import time_machine

from sprachweg.extensions import db
from sprachweg.models import (
    ActivityType,
    PlanItem,
    PlanItemStatus,
    PlanTemplateItem,
    StudyPlan,
    StudySession,
)
from sprachweg.services.plans import (
    activate_plan,
    delete_plan,
    ensure_plan_items,
    regenerate_future_for_template,
    set_item_status,
)


def _make_plan(language, starts_on: date) -> StudyPlan:
    plan = StudyPlan(language_id=language.id, name="Test plan", starts_on=starts_on, is_active=True)
    db.session.add(plan)
    db.session.flush()
    vocab = ActivityType.query.filter_by(key="vocab").first()
    for weekday in range(7):  # every day, for simplicity
        db.session.add(
            PlanTemplateItem(
                plan_id=plan.id, weekday=weekday, activity_type_id=vocab.id, planned_minutes=30
            )
        )
    db.session.commit()
    return plan


def test_no_items_generated_before_plan_start(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        plan = _make_plan(language, starts_on=date(2027, 1, 10))
        ensure_plan_items(plan, start=date(2027, 1, 1), end=date(2027, 1, 20))
        dates = {i.date for i in PlanItem.query.filter_by(plan_id=plan.id).all()}
    assert min(dates) == date(2027, 1, 10)


def test_no_items_generated_more_than_a_week_into_the_future(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        plan = _make_plan(language, starts_on=date(2027, 1, 1))
        ensure_plan_items(plan, start=date(2027, 1, 1), end=date(2027, 2, 1))
        dates = {i.date for i in PlanItem.query.filter_by(plan_id=plan.id).all()}
    assert max(dates) == date(2027, 1, 22)  # today + 7


def test_expansion_is_idempotent(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        plan = _make_plan(language, starts_on=date(2027, 1, 1))
        ensure_plan_items(plan, start=date(2027, 1, 1), end=date(2027, 1, 15))
        ensure_plan_items(plan, start=date(2027, 1, 1), end=date(2027, 1, 15))
        count = PlanItem.query.filter_by(plan_id=plan.id).count()
    assert count == 15  # one per day, not doubled


def test_editing_template_only_regenerates_future_pending_items(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        plan = _make_plan(language, starts_on=date(2027, 1, 1))
        ensure_plan_items(plan, start=date(2027, 1, 1), end=date(2027, 1, 20))

        past_item = PlanItem.query.filter_by(plan_id=plan.id, date=date(2027, 1, 10)).first()
        past_item.status = PlanItemStatus.DONE
        db.session.commit()

        template = plan.template_items[0]
        template.planned_minutes = 60
        regenerate_future_for_template(template)

        # past, completed item survives untouched
        survived = db.session.get(PlanItem, past_item.id)
        assert survived is not None
        assert survived.status == PlanItemStatus.DONE

        # future pending items for this template were wiped, ready to regenerate
        future_remaining = PlanItem.query.filter(
            PlanItem.template_item_id == template.id, PlanItem.date >= date(2027, 1, 15)
        ).count()
        assert future_remaining == 0


def test_marking_done_creates_linked_session(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        plan = _make_plan(language, starts_on=date(2027, 1, 15))
        ensure_plan_items(plan, start=date(2027, 1, 15), end=date(2027, 1, 15))
        item = PlanItem.query.filter_by(plan_id=plan.id, date=date(2027, 1, 15)).first()

        set_item_status(item, PlanItemStatus.DONE)
        assert item.session is not None
        assert item.session.minutes == item.planned_minutes

        # un-checking removes the linked session
        set_item_status(item, PlanItemStatus.PENDING)
        assert item.session is None


def test_marking_partial_uses_actual_minutes(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        plan = _make_plan(language, starts_on=date(2027, 1, 15))
        ensure_plan_items(plan, start=date(2027, 1, 15), end=date(2027, 1, 15))
        item = PlanItem.query.filter_by(plan_id=plan.id, date=date(2027, 1, 15)).first()

        set_item_status(item, PlanItemStatus.PARTIAL, actual_minutes=12)
        assert item.session.minutes == 12
        assert item.status == PlanItemStatus.PARTIAL


def test_delete_plan_removes_plan_and_items_but_keeps_sessions(app, language, db):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        plan = _make_plan(language, starts_on=date(2027, 1, 15))
        ensure_plan_items(plan, start=date(2027, 1, 15), end=date(2027, 1, 15))
        item = PlanItem.query.filter_by(plan_id=plan.id, date=date(2027, 1, 15)).first()
        set_item_status(item, PlanItemStatus.DONE)
        session_id = item.session.id
        plan_id = plan.id

        delete_plan(plan)

        assert db.session.get(StudyPlan, plan_id) is None
        assert PlanItem.query.filter_by(plan_id=plan_id).count() == 0
        assert PlanTemplateItem.query.filter_by(plan_id=plan_id).count() == 0

        # the logged session survives, just unlinked from the (now-gone) plan item
        survived = db.session.get(StudySession, session_id)
        assert survived is not None
        assert survived.plan_item_id is None
        assert survived.minutes == 30


def test_activate_plan_swaps_the_active_plan_for_the_language(app, language, db):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        old_plan = _make_plan(language, starts_on=date(2027, 1, 1))
        new_plan = _make_plan(language, starts_on=date(2027, 1, 10))
        new_plan.is_active = False
        new_plan.ends_on = date(2027, 1, 12)
        db.session.commit()

        activate_plan(new_plan)

        assert new_plan.is_active is True
        assert new_plan.ends_on is None
        refreshed_old = db.session.get(StudyPlan, old_plan.id)
        assert refreshed_old.is_active is False
