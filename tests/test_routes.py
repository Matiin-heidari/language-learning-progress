from __future__ import annotations

from datetime import date

import time_machine
from conftest import TEST_PASSWORD

from sprachweg.models import PlanItem, PlanItemStatus, StudyPlan, StudySession


def test_landing_page_for_anonymous_visitor(app, client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Sprachweg" in r.data


def test_dashboard_requires_login(app, client):
    r = client.get("/dashboard")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_signup_creates_account_and_seeds_german(app, client):
    r = client.post(
        "/signup",
        data={
            "username": "newlearner",
            "password": "a-decent-password",
            "confirm_password": "a-decent-password",
        },
    )
    assert r.status_code == 302
    from sprachweg.models import Language, User

    created = User.query.filter_by(username="newlearner").first()
    assert created is not None
    assert Language.query.filter_by(user_id=created.id, code="de").first() is not None


def test_login_with_wrong_password_fails(app, user, client):
    r = client.post("/login", data={"username": user.username, "password": "wrong"})
    assert r.status_code == 200  # re-renders the form
    assert b"Wrong username or password" in r.data


def test_dashboard_onboarding_when_no_language(app, auth_client):
    r = auth_client.get("/dashboard")
    assert r.status_code == 200
    assert b"Welcome" in r.data


def test_dashboard_renders_with_seeded_language(app, language, auth_client):
    r = auth_client.get("/dashboard")
    assert r.status_code == 200
    assert b"German" in r.data


def test_create_session_persists_and_redirects(app, language, auth_client):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        activity_id = language.levels[0].skill_targets[0].activity_type_id
        r = auth_client.post(
            "/sessions/new",
            data={
                "activity_type_id": str(activity_id),
                "study_date": "2027-01-10",
                "minutes": "45",
            },
        )
        assert r.status_code == 302
        session = StudySession.query.filter_by(language_id=language.id).first()
        assert session is not None
        assert session.minutes == 45
        assert session.study_date == date(2027, 1, 10)
        assert session.user_id == language.user_id


def test_create_session_future_date_is_clamped_to_today(app, language, auth_client):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        activity_id = language.levels[0].skill_targets[0].activity_type_id
        r = auth_client.post(
            "/sessions/new",
            data={
                "activity_type_id": str(activity_id),
                "study_date": "2099-01-01",
                "minutes": "30",
            },
        )
        assert r.status_code == 302
        session = StudySession.query.filter_by(language_id=language.id).first()
        assert session.study_date == date(2027, 1, 15)


def test_edit_session(app, language, auth_client, db):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        activity_id = language.levels[0].skill_targets[0].activity_type_id
        auth_client.post(
            "/sessions/new",
            data={
                "activity_type_id": str(activity_id),
                "study_date": "2027-01-10",
                "minutes": "20",
            },
        )
        session = StudySession.query.filter_by(language_id=language.id).first()

        r = auth_client.post(
            f"/sessions/{session.id}/edit",
            data={
                "activity_type_id": str(activity_id),
                "study_date": "2027-01-11",
                "minutes": "40",
            },
        )
        assert r.status_code == 302
        updated = db.session.get(StudySession, session.id)
        assert updated.minutes == 40
        assert updated.study_date == date(2027, 1, 11)


def test_delete_session(app, language, auth_client, db):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        activity_id = language.levels[0].skill_targets[0].activity_type_id
        auth_client.post(
            "/sessions/new",
            data={
                "activity_type_id": str(activity_id),
                "study_date": "2027-01-10",
                "minutes": "20",
            },
        )
        session = StudySession.query.filter_by(language_id=language.id).first()

        r = auth_client.post(f"/sessions/{session.id}/delete")
        assert r.status_code == 302
        assert db.session.get(StudySession, session.id) is None


def test_ticking_plan_item_done_creates_session_and_survives_reload(app, language, auth_client, db):
    from sprachweg.models import ActivityType, PlanTemplateItem

    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        vocab = ActivityType.query.filter_by(key="vocab").first()
        plan = StudyPlan(
            language_id=language.id, name="P", starts_on=date(2027, 1, 15), is_active=True
        )
        db.session.add(plan)
        db.session.flush()
        db.session.add(
            PlanTemplateItem(
                plan_id=plan.id,
                weekday=date(2027, 1, 15).weekday(),
                activity_type_id=vocab.id,
                planned_minutes=30,
            )
        )
        db.session.commit()

        r = auth_client.get("/today")
        assert r.status_code == 200
        item = PlanItem.query.filter_by(plan_id=plan.id, date=date(2027, 1, 15)).first()
        assert item is not None

        r = auth_client.post(
            f"/plan-items/{item.id}/status",
            data={"status": "done"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        reloaded = db.session.get(PlanItem, item.id)
        assert reloaded.status == PlanItemStatus.DONE
        assert reloaded.session is not None
        assert reloaded.session.minutes == 30


def test_csrf_is_enforced_on_state_changing_requests():
    """A separate app instance with CSRF actually enabled, to prove the app
    rejects a POST without a valid token (the rest of the suite disables
    CSRF for convenience, per Flask-WTF's documented testing pattern).
    """
    from sprachweg import create_app
    from sprachweg.extensions import db as real_db
    from sprachweg.models import User
    from sprachweg.seed import seed_global_activity_types, seed_user_language

    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        real_db.create_all()
        seed_global_activity_types()
        u = User(username="csrftest")
        u.set_password(TEST_PASSWORD)
        real_db.session.add(u)
        real_db.session.flush()
        seed_user_language(u)
        real_db.session.commit()

        client = app.test_client()
        # CSRF is enforced even on the login form itself.
        r = client.post("/login", data={"username": u.username, "password": TEST_PASSWORD})
        assert r.status_code == 400
        real_db.session.remove()
        real_db.drop_all()


def test_mark_level_complete_route(app, language, auth_client, db):
    from sprachweg.models import Level

    a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
    r = auth_client.post(f"/levels/{a1.id}/mark-complete")
    assert r.status_code == 302

    sessions = StudySession.query.filter_by(language_id=language.id).all()
    assert sum(s.minutes for s in sessions) == a1.target_minutes

    # the catch-up entries are plain sessions: deletable from the Log page
    for s in sessions:
        auth_client.post(f"/sessions/{s.id}/delete")
    assert StudySession.query.filter_by(language_id=language.id).count() == 0


def test_apply_to_days_creates_a_plan_and_crosses_days_with_activities(app, language, auth_client):
    from sprachweg.models import ActivityType, PlanTemplateItem, StudyPlan

    vocab = ActivityType.query.filter_by(key="vocab").first()
    grammar = ActivityType.query.filter_by(key="grammar").first()

    r = auth_client.post(
        "/plan/apply-to-days",
        data={
            "weekday": ["0", "2", "4"],
            "activity_type_id[]": [str(vocab.id), str(grammar.id)],
            "planned_minutes[]": ["20", "30"],
        },
    )
    assert r.status_code == 302

    plan = StudyPlan.query.filter_by(language_id=language.id, is_active=True).first()
    assert plan is not None
    items = PlanTemplateItem.query.filter_by(plan_id=plan.id).all()
    assert len(items) == 6  # 3 days x 2 activities
    assert {i.weekday for i in items} == {0, 2, 4}
    vocab_items = [i for i in items if i.activity_type_id == vocab.id]
    assert all(i.planned_minutes == 20 for i in vocab_items)

    # calling it again is additive, not a replace (consistent with the grid's own "+Add")
    auth_client.post(
        "/plan/apply-to-days",
        data={
            "weekday": ["0"],
            "activity_type_id[]": [str(vocab.id)],
            "planned_minutes[]": ["15"],
        },
    )
    assert PlanTemplateItem.query.filter_by(plan_id=plan.id).count() == 7


def test_user_cannot_mutate_another_users_plan(app, db, client):
    """A plan-mutation route scoped by id alone (not also by owning language)
    would let one account tamper with another's plan by guessing the id."""
    from sprachweg.models import ActivityType, PlanTemplateItem, User
    from sprachweg.seed import seed_global_activity_types, seed_user_language

    seed_global_activity_types()
    owner = User(username="owner")
    owner.set_password(TEST_PASSWORD)
    attacker = User(username="attacker")
    attacker.set_password(TEST_PASSWORD)
    db.session.add_all([owner, attacker])
    db.session.flush()
    owner_language = seed_user_language(owner)
    seed_user_language(attacker)

    plan = StudyPlan(language_id=owner_language.id, name="Owner's plan", starts_on=date(2027, 1, 1))
    db.session.add(plan)
    db.session.flush()
    vocab = ActivityType.query.filter_by(key="vocab").first()
    item = PlanTemplateItem(
        plan_id=plan.id, weekday=0, activity_type_id=vocab.id, planned_minutes=30
    )
    db.session.add(item)
    db.session.commit()

    client.post("/login", data={"username": "attacker", "password": TEST_PASSWORD})
    r = client.post(f"/plan/{plan.id}/delete")
    assert r.status_code == 404
    assert db.session.get(StudyPlan, plan.id) is not None
