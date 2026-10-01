"""SQLAlchemy models.

Design notes (see PLAN.md §5 for the original single-user rationale, now
extended to multi-user accounts):
- Every learner is a `User` row. `Language`, `ActivityType` (when custom) and
  `StudySession` are scoped to a `user_id` so each account's progress, plans
  and settings are fully independent. `ActivityType` rows with `user_id IS
  NULL` are the shared global defaults (vocab, grammar, ...) every account
  sees; a user can add their own on top via Settings.
- Per-user preferences (timezone, streak threshold, daily goal, theme, ...)
  live directly as columns on `User` rather than a generic key/value table --
  there's a small fixed set of them and they're always read for "the current
  user", so a dedicated table added nothing but indirection.
- `study_session.study_date` is a plain DATE, always computed from the
  logged-in user's timezone (never derived from a UTC timestamp) so a session
  logged at 00:30 local still counts for the correct day.
- Level hours are stored *per level*, not cumulatively, so editing one
  level's target doesn't require touching the others.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from sprachweg.extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class PlanItemStatus(enum.StrEnum):
    PENDING = "pending"
    DONE = "done"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(64), nullable=False, default="")

    # Per-user preferences -- see module docstring for why these are plain
    # columns rather than a generic Setting table.
    timezone = db.Column(db.String(64), nullable=False, default="Europe/Berlin")
    week_start = db.Column(db.String(4), nullable=False, default="mon")  # "mon" | "sun"
    streak_min_minutes = db.Column(db.Integer, nullable=False, default=10)
    daily_goal_minutes = db.Column(db.Integer, nullable=False, default=60)
    theme = db.Column(db.String(8), nullable=False, default="system")  # system|light|dark

    # Social: whether /u/<username> and the leaderboard show this account to
    # others. Off by default is friendlier, but this is a small-group personal
    # tool, so default True keeps "see each other's progress" working out of
    # the box; flip it in Settings to opt out.
    is_public = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    languages = db.relationship(
        "Language", back_populates="user", cascade="all, delete-orphan", order_by="Language.id"
    )
    sessions = db.relationship("StudySession", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username}>"


class Language(db.Model):
    __tablename__ = "language"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_language_user_code"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    code = db.Column(db.String(8), nullable=False)  # "de"
    name = db.Column(db.String(64), nullable=False)  # "German"
    native_name = db.Column(db.String(64), nullable=False)  # "Deutsch"
    flag_emoji = db.Column(db.String(8), nullable=False, default="🏳")
    accent_color = db.Column(db.String(9), nullable=True)
    goal_level_id = db.Column(
        db.Integer,
        db.ForeignKey("level.id", use_alter=True, name="fk_language_goal_level"),
        nullable=True,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="languages")
    levels = db.relationship(
        "Level",
        back_populates="language",
        foreign_keys="Level.language_id",
        order_by="Level.sort_order",
        cascade="all, delete-orphan",
    )
    goal_level = db.relationship("Level", foreign_keys=[goal_level_id], post_update=True)
    sessions = db.relationship(
        "StudySession", back_populates="language", cascade="all, delete-orphan"
    )
    plans = db.relationship("StudyPlan", back_populates="language", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Language {self.code}>"


class Level(db.Model):
    __tablename__ = "level"
    __table_args__ = (UniqueConstraint("language_id", "code", name="uq_level_language_code"),)

    id = db.Column(db.Integer, primary_key=True)
    language_id = db.Column(db.Integer, db.ForeignKey("language.id"), nullable=False)
    code = db.Column(db.String(4), nullable=False)  # "A1".."C2"
    name = db.Column(db.String(64), nullable=False)  # "Beginner"
    sort_order = db.Column(db.Integer, nullable=False)
    target_hours = db.Column(db.Numeric(6, 1), nullable=False)
    is_hidden = db.Column(db.Boolean, nullable=False, default=False)  # e.g. C2 when goal is C1

    language = db.relationship("Language", back_populates="levels", foreign_keys=[language_id])
    skill_targets = db.relationship(
        "LevelSkillTarget", back_populates="level", cascade="all, delete-orphan"
    )

    @property
    def target_minutes(self) -> int:
        return int(round(float(self.target_hours) * 60))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Level {self.code}>"


class ActivityType(db.Model):
    __tablename__ = "activity_type"

    id = db.Column(db.Integer, primary_key=True)
    # NULL = shared global default (vocab, grammar, ...), seeded once and
    # visible to every account. Non-null = a custom type only that user sees.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    key = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(64), nullable=False)  # "Vocabulary"
    icon = db.Column(db.String(32), nullable=False, default="book")  # lucide icon name
    color_slot = db.Column(db.Integer, nullable=False)  # 1..8 -> CSS var --series-N
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ActivityType {self.key}>"


class LevelSkillTarget(db.Model):
    __tablename__ = "level_skill_target"
    __table_args__ = (UniqueConstraint("level_id", "activity_type_id", name="uq_level_activity"),)

    id = db.Column(db.Integer, primary_key=True)
    level_id = db.Column(db.Integer, db.ForeignKey("level.id"), nullable=False)
    activity_type_id = db.Column(db.Integer, db.ForeignKey("activity_type.id"), nullable=False)
    percent = db.Column(db.Numeric(5, 2), nullable=False)

    level = db.relationship("Level", back_populates="skill_targets")
    activity_type = db.relationship("ActivityType")


class StudySession(db.Model):
    __tablename__ = "study_session"
    __table_args__ = (
        CheckConstraint("minutes > 0 AND minutes <= 960", name="ck_session_minutes_range"),
        db.Index("ix_session_language_date", "language_id", "study_date"),
        db.Index("ix_session_user_date", "user_id", "study_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Denormalized alongside language_id (which already implies the owner)
    # so per-user aggregates -- the leaderboard, an "all languages" streak --
    # don't need a join through `language`.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    language_id = db.Column(db.Integer, db.ForeignKey("language.id"), nullable=False)
    activity_type_id = db.Column(db.Integer, db.ForeignKey("activity_type.id"), nullable=False)
    study_date = db.Column(db.Date, nullable=False)
    minutes = db.Column(db.Integer, nullable=False)
    note = db.Column(db.Text, nullable=True)
    resource = db.Column(db.String(200), nullable=True)
    # True for catch-up entries created by "mark level complete" (PLAN.md-style
    # backfill, not a real study session). Counted toward total/level progress
    # and streak "day was active", but excluded from pace/rate stats (weekly
    # chart, activity split, this-week tile, ETA pace) so one lump entry
    # doesn't dwarf every real day on the same scale.
    is_backfill = db.Column(db.Boolean, nullable=False, default=False)
    plan_item_id = db.Column(db.Integer, db.ForeignKey("plan_item.id"), nullable=True, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="sessions")
    language = db.relationship("Language", back_populates="sessions")
    activity_type = db.relationship("ActivityType")
    plan_item = db.relationship("PlanItem", back_populates="session", foreign_keys=[plan_item_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StudySession {self.study_date} {self.minutes}m>"


class StudyPlan(db.Model):
    __tablename__ = "study_plan"

    id = db.Column(db.Integer, primary_key=True)
    language_id = db.Column(db.Integer, db.ForeignKey("language.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False, default="My plan")
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    language = db.relationship("Language", back_populates="plans")
    template_items = db.relationship(
        "PlanTemplateItem",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanTemplateItem.weekday, PlanTemplateItem.sort_order",
    )
    items = db.relationship("PlanItem", back_populates="plan", cascade="all, delete-orphan")

    @property
    def weekly_goal_minutes(self) -> int:
        return sum(i.planned_minutes for i in self.template_items)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StudyPlan {self.name}>"


class PlanTemplateItem(db.Model):
    __tablename__ = "plan_template_item"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_template_weekday_range"),
    )

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("study_plan.id"), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)  # 0=Mon..6=Sun
    activity_type_id = db.Column(db.Integer, db.ForeignKey("activity_type.id"), nullable=False)
    planned_minutes = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(120), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    plan = db.relationship("StudyPlan", back_populates="template_items")
    activity_type = db.relationship("ActivityType")
    generated_items = db.relationship("PlanItem", back_populates="template_item")


class PlanItem(db.Model):
    __tablename__ = "plan_item"
    __table_args__ = (
        UniqueConstraint("template_item_id", "date", name="uq_plan_item_template_date"),
        db.Index("ix_plan_item_plan_date", "plan_id", "date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("study_plan.id"), nullable=False)
    template_item_id = db.Column(db.Integer, db.ForeignKey("plan_template_item.id"), nullable=True)
    date = db.Column(db.Date, nullable=False)
    activity_type_id = db.Column(db.Integer, db.ForeignKey("activity_type.id"), nullable=False)
    planned_minutes = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(120), nullable=True)
    status = db.Column(
        db.Enum(PlanItemStatus, native_enum=False, length=16),
        nullable=False,
        default=PlanItemStatus.PENDING,
    )

    plan = db.relationship("StudyPlan", back_populates="items")
    template_item = db.relationship("PlanTemplateItem", back_populates="generated_items")
    activity_type = db.relationship("ActivityType")
    session = db.relationship(
        "StudySession",
        back_populates="plan_item",
        uselist=False,
        foreign_keys=[StudySession.plan_item_id],
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PlanItem {self.date} {self.status.value}>"


class MilestoneEvent(db.Model):
    __tablename__ = "milestone_event"

    id = db.Column(db.Integer, primary_key=True)
    language_id = db.Column(db.Integer, db.ForeignKey("language.id"), nullable=False)
    # kind: level_hours_reached | streak | hours_total | exam_passed
    kind = db.Column(db.String(32), nullable=False)
    ref = db.Column(db.String(32), nullable=False)  # "A1" | "30" | "100"
    achieved_on = db.Column(db.Date, nullable=False)
    seen = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    language = db.relationship("Language")


def today_local() -> date:
    """The current date in the logged-in user's timezone.

    Falls back to Config.TIMEZONE / UTC outside of a request context (e.g.
    tests, CLI commands) or when no one is logged in, so this stays safe to
    call from anywhere `today_local()` always has been.
    """
    from zoneinfo import ZoneInfo

    from flask import current_app, has_request_context

    tz_name = None
    if has_request_context():
        try:
            from flask_login import current_user

            if current_user and current_user.is_authenticated:
                tz_name = current_user.timezone
        except Exception:
            pass
    tz_name = tz_name or current_app.config.get("TIMEZONE", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = UTC
    return datetime.now(tz).date()
