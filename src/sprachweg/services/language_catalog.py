"""The shared language catalog: admin-managed templates (a `Language` row
with `user_id IS NULL`, plus its `Level`/`LevelSkillTarget` rows) that any
user can clone into their own account via "add a language". Mirrors the
existing global/per-user split already used for `ActivityType`.

German is the one language with hand-researched hour targets (see PLAN.md
§2/§2.4 for the Goethe-Institut/FSI/Cambridge-based research behind the
numbers below) and is always present in the catalog. Any other language an
admin adds goes through the same `create_language_template` path.
"""

from __future__ import annotations

from sprachweg.extensions import db
from sprachweg.models import ActivityType, Language, Level, LevelSkillTarget, User

# CEFR level codes in order -- every template (German or admin-added) uses
# this same ladder, just with different hour targets per level.
LEVEL_CODES = ["A1", "A2", "B1", "B2", "C1", "C2"]
LEVEL_NAMES = {
    "A1": "Beginner",
    "A2": "Elementary",
    "B1": "Intermediate",
    "B2": "Upper Intermediate",
    "C1": "Advanced",
    "C2": "Mastery",
}

# key, name, icon (lucide), color slot (1..8, fixed categorical order)
ACTIVITY_TYPES = [
    ("vocab", "Vocabulary", "book-a", 1),
    ("grammar", "Grammar", "spell-check", 2),
    ("listening", "Listening", "headphones", 3),
    ("reading", "Reading", "book-open", 4),
    ("speaking", "Speaking", "mic", 5),
    ("writing", "Writing", "pen-line", 6),
]

# German hour targets per level (see PLAN.md §2.3) and percent split per
# activity (see PLAN.md §2.4).
GERMAN_LEVEL_HOURS = {
    "A1": 120.0,
    "A2": 160.0,
    "B1": 240.0,
    "B2": 300.0,
    "C1": 380.0,
    "C2": 500.0,  # hidden: goal is C1, but kept for later
}
GERMAN_HIDDEN_LEVELS = {"C2"}
GERMAN_SKILL_MIX = {
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


def list_language_templates() -> list[Language]:
    """All catalog templates (global, `user_id IS NULL`), oldest first."""
    return Language.query.filter_by(user_id=None).order_by(Language.id).all()


def list_available_templates_for(user: User) -> list[Language]:
    """Templates `user` hasn't already added to their own account."""
    already_have = {lang.code for lang in Language.query.filter_by(user_id=user.id).all()}
    return [t for t in list_language_templates() if t.code not in already_have]


def ensure_german_template() -> Language:
    """German is always in the catalog. Idempotent."""
    template = Language.query.filter_by(user_id=None, code="de").first()
    if template is not None:
        return template
    return create_language_template(
        code="de",
        name="German",
        native_name="Deutsch",
        flag_emoji="🇩🇪",
        level_hours=GERMAN_LEVEL_HOURS,
        hidden_levels=GERMAN_HIDDEN_LEVELS,
        skill_mix=GERMAN_SKILL_MIX,
        goal_level_code="C1",
    )


def create_language_template(
    *,
    code: str,
    name: str,
    native_name: str,
    flag_emoji: str,
    level_hours: dict[str, float],
    hidden_levels: set[str] | None = None,
    skill_mix: dict[str, dict[str, float]] | None = None,
    goal_level_code: str | None = "C1",
) -> Language:
    """Create a new catalog template (admin action). `level_hours` maps CEFR
    code -> target hours for that level; only levels present in the dict are
    created (so an admin can do just A1-C1, say). Without an explicit
    `skill_mix`, each level's hours are split evenly across the global
    activity types.
    """
    hidden_levels = hidden_levels or set()
    existing = Language.query.filter_by(user_id=None, code=code).first()
    if existing is not None:
        return existing

    language = Language(
        user_id=None, code=code, name=name, native_name=native_name, flag_emoji=flag_emoji
    )
    db.session.add(language)
    db.session.flush()

    activities = seed_global_activity_types()
    levels_by_code: dict[str, Level] = {}
    for order, level_code in enumerate(LEVEL_CODES):
        if level_code not in level_hours:
            continue
        level = Level(
            language_id=language.id,
            code=level_code,
            name=LEVEL_NAMES[level_code],
            sort_order=order,
            target_hours=level_hours[level_code],
            is_hidden=level_code in hidden_levels,
        )
        db.session.add(level)
        db.session.flush()
        levels_by_code[level_code] = level

        mix = (skill_mix or {}).get(level_code)
        if mix:
            for act_key, percent in mix.items():
                activity = activities.get(act_key)
                if activity is not None:
                    db.session.add(
                        LevelSkillTarget(
                            level_id=level.id, activity_type_id=activity.id, percent=percent
                        )
                    )
        else:
            # No mix given: split this level's hours evenly across every
            # global activity type, so the per-skill mini-bars aren't empty.
            even_share = round(100 / len(activities), 2) if activities else 0
            for activity in activities.values():
                db.session.add(
                    LevelSkillTarget(
                        level_id=level.id, activity_type_id=activity.id, percent=even_share
                    )
                )

    if goal_level_code and goal_level_code in levels_by_code:
        language.goal_level_id = levels_by_code[goal_level_code].id

    db.session.commit()
    return language


def clone_template_for_user(user: User, template: Language) -> Language:
    """Copy a catalog template's levels + skill mix into a new language
    owned by `user`. Idempotent per (user, code).
    """
    existing = Language.query.filter_by(user_id=user.id, code=template.code).first()
    if existing is not None:
        return existing

    language = Language(
        user_id=user.id,
        code=template.code,
        name=template.name,
        native_name=template.native_name,
        flag_emoji=template.flag_emoji,
    )
    db.session.add(language)
    db.session.flush()

    level_id_map: dict[int, int] = {}
    for template_level in sorted(template.levels, key=lambda lv: lv.sort_order):
        level = Level(
            language_id=language.id,
            code=template_level.code,
            name=template_level.name,
            sort_order=template_level.sort_order,
            target_hours=template_level.target_hours,
            is_hidden=template_level.is_hidden,
        )
        db.session.add(level)
        db.session.flush()
        level_id_map[template_level.id] = level.id
        for st in template_level.skill_targets:
            db.session.add(
                LevelSkillTarget(
                    level_id=level.id,
                    activity_type_id=st.activity_type_id,
                    percent=st.percent,
                )
            )

    if template.goal_level_id and template.goal_level_id in level_id_map:
        language.goal_level_id = level_id_map[template.goal_level_id]

    db.session.commit()
    return language
