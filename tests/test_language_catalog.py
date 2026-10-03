from __future__ import annotations

from sprachweg.models import Language, Level, LevelSkillTarget, User
from sprachweg.services.language_catalog import (
    clone_template_for_user,
    create_language_template,
    ensure_german_template,
    list_available_templates_for,
)


def test_ensure_german_template_creates_a_global_language(app, db):
    template = ensure_german_template()
    assert template.user_id is None
    assert template.code == "de"
    levels = Level.query.filter_by(language_id=template.id).all()
    assert {lv.code for lv in levels} == {"A1", "A2", "B1", "B2", "C1", "C2"}
    a1 = next(lv for lv in levels if lv.code == "A1")
    assert float(a1.target_hours) == 120.0
    assert len(a1.skill_targets) == 6  # vocab/grammar/listening/reading/speaking/writing


def test_ensure_german_template_is_idempotent(app, db):
    first = ensure_german_template()
    second = ensure_german_template()
    assert first.id == second.id
    assert Language.query.filter_by(user_id=None, code="de").count() == 1


def test_create_language_template_with_partial_levels_and_even_skill_split(app, db):
    template = create_language_template(
        code="es",
        name="Spanish",
        native_name="Español",
        flag_emoji="🇪🇸",
        level_hours={"A1": 80.0, "A2": 100.0},  # only two levels, on purpose
        goal_level_code="A2",
    )
    levels = Level.query.filter_by(language_id=template.id).all()
    assert {lv.code for lv in levels} == {"A1", "A2"}
    assert template.goal_level.code == "A2"

    a1 = next(lv for lv in levels if lv.code == "A1")
    targets = LevelSkillTarget.query.filter_by(level_id=a1.id).all()
    assert len(targets) == 6  # split evenly across all 6 global activity types
    percents = {float(t.percent) for t in targets}
    assert len(percents) == 1  # all equal shares


def test_list_available_templates_excludes_languages_user_already_has(app, db):
    user = User(username="catalogtester")
    user.set_password("whatever-password")
    db.session.add(user)
    db.session.flush()

    german = ensure_german_template()
    create_language_template(
        code="es",
        name="Spanish",
        native_name="Español",
        flag_emoji="🇪🇸",
        level_hours={"A1": 80.0},
        goal_level_code="A1",
    )

    assert {t.code for t in list_available_templates_for(user)} == {"de", "es"}

    clone_template_for_user(user, german)
    assert {t.code for t in list_available_templates_for(user)} == {"es"}


def test_clone_template_for_user_copies_levels_and_skill_mix_independently(app, db):
    user = User(username="cloner")
    user.set_password("whatever-password")
    db.session.add(user)
    db.session.flush()

    template = ensure_german_template()
    language = clone_template_for_user(user, template)

    assert language.user_id == user.id
    assert language.id != template.id  # a real, independent copy
    assert language.goal_level.code == "C1"

    # editing the clone's hours must not affect the template or other clones
    clone_a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
    clone_a1.target_hours = 999
    db.session.commit()

    template_a1 = Level.query.filter_by(language_id=template.id, code="A1").first()
    assert float(template_a1.target_hours) == 120.0


def test_clone_template_for_user_is_idempotent_per_code(app, db):
    user = User(username="cloner2")
    user.set_password("whatever-password")
    db.session.add(user)
    db.session.flush()

    template = ensure_german_template()
    first = clone_template_for_user(user, template)
    second = clone_template_for_user(user, template)
    assert first.id == second.id
    assert Language.query.filter_by(user_id=user.id, code="de").count() == 1
