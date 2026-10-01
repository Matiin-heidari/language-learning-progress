"""Idempotent seed data: global activity types + a new user's German +
CEFR levels + skill mix.

See PLAN.md §2 for the hour-target research and §2.4 for the skill mix.
Activity types are a shared global catalog (seeded once, `flask seed`);
German + levels are seeded per-account (`seed_user_language`, called on
signup) so every user's progress is fully independent.
"""

from __future__ import annotations

from sprachweg.extensions import db
from sprachweg.models import ActivityType, Language, Level, LevelSkillTarget, User

# level code, name, target hours for that level, hidden-by-default
LEVELS = [
    ("A1", "Beginner", 120.0, False),
    ("A2", "Elementary", 160.0, False),
    ("B1", "Intermediate", 240.0, False),
    ("B2", "Upper Intermediate", 300.0, False),
    ("C1", "Advanced", 380.0, False),
    ("C2", "Mastery", 500.0, True),  # hidden: goal is C1, but kept for later
]

# key, name, icon (lucide), color slot (1..8, fixed categorical order)
ACTIVITY_TYPES = [
    ("vocab", "Vocabulary", "book-a", 1),
    ("grammar", "Grammar", "spell-check", 2),
    ("listening", "Listening", "headphones", 3),
    ("reading", "Reading", "book-open", 4),
    ("speaking", "Speaking", "mic", 5),
    ("writing", "Writing", "pen-line", 6),
]

# percent split per level, keyed by activity key. See PLAN.md §2.4.
SKILL_MIX = {
    "A1": {
        "vocab": 25,
        "grammar": 25,
        "listening": 15,
        "reading": 10,
        "speaking": 15,
        "writing": 10,
    },
    "A2": {
        "vocab": 20,
        "grammar": 20,
        "listening": 18,
        "reading": 15,
        "speaking": 15,
        "writing": 12,
    },
    "B1": {
        "vocab": 15,
        "grammar": 15,
        "listening": 20,
        "reading": 20,
        "speaking": 15,
        "writing": 15,
    },
    "B2": {
        "vocab": 12,
        "grammar": 10,
        "listening": 22,
        "reading": 22,
        "speaking": 17,
        "writing": 17,
    },
    "C1": {
        "vocab": 10,
        "grammar": 8,
        "listening": 22,
        "reading": 22,
        "speaking": 18,
        "writing": 20,
    },
    "C2": {
        "vocab": 10,
        "grammar": 8,
        "listening": 22,
        "reading": 22,
        "speaking": 18,
        "writing": 20,
    },
}


def seed_global_activity_types() -> dict[str, ActivityType]:
    """The shared default activity types every account sees (`user_id` is
    NULL). Idempotent -- safe to call on every app start / `flask seed`.
    """
    by_key: dict[str, ActivityType] = {}
    for order, (key, name, icon, slot) in enumerate(ACTIVITY_TYPES):
        activity = ActivityType.query.filter_by(key=key, user_id=None).first()
        if activity is None:
            activity = ActivityType(
                key=key, name=name, icon=icon, color_slot=slot, sort_order=order, user_id=None
            )
            db.session.add(activity)
        by_key[key] = activity
    db.session.flush()
    return by_key


def seed_user_language(user: User, *, code: str = "de") -> Language:
    """Give `user` a German language with CEFR levels + skill mix. Called on
    signup. Idempotent per (user, code) pair.
    """
    language = Language.query.filter_by(user_id=user.id, code=code).first()
    if language is None:
        language = Language(
            user_id=user.id, code=code, name="German", native_name="Deutsch", flag_emoji="🇩🇪"
        )
        db.session.add(language)
        db.session.flush()

    activities = seed_global_activity_types()

    levels_by_code: dict[str, Level] = {}
    for order, (code, name, hours, hidden) in enumerate(LEVELS):
        level = Level.query.filter_by(language_id=language.id, code=code).first()
        if level is None:
            level = Level(
                language_id=language.id,
                code=code,
                name=name,
                sort_order=order,
                target_hours=hours,
                is_hidden=hidden,
            )
            db.session.add(level)
            db.session.flush()
        levels_by_code[code] = level

        # Skill mix (only create if missing; never overwrite user edits)
        existing = {st.activity_type_id for st in level.skill_targets}
        for act_key, percent in SKILL_MIX.get(code, {}).items():
            activity = activities[act_key]
            if activity.id not in existing:
                db.session.add(
                    LevelSkillTarget(
                        level_id=level.id, activity_type_id=activity.id, percent=percent
                    )
                )

    if language.goal_level_id is None:
        language.goal_level_id = levels_by_code["C1"].id

    db.session.commit()
    return language
