"""Progress calculations: total-to-goal, per-level fill, per-skill split, ETA.

Pure functions (no Flask/request access beyond `models.today_local`) so they
are easy to unit test with a fabricated list of sessions. See PLAN.md §6.1-6.3
and §6.6 for the algorithms this implements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sprachweg.extensions import db
from sprachweg.models import ActivityType, Language, Level, StudySession, today_local


@dataclass
class SkillProgress:
    activity_type: ActivityType
    target_minutes: int
    earned_minutes: int = 0

    @property
    def pct(self) -> float:
        if self.target_minutes <= 0:
            return 0.0
        return min(100.0, self.earned_minutes / self.target_minutes * 100)


@dataclass
class LevelProgress:
    level: Level
    filled_minutes: int = 0
    status: str = "locked"  # "done" | "current" | "locked"
    skills: dict[int, SkillProgress] = field(default_factory=dict)

    @property
    def pct(self) -> float:
        cap = self.level.target_minutes
        if cap <= 0:
            return 0.0
        return min(100.0, self.filled_minutes / cap * 100)

    @property
    def remaining_minutes(self) -> int:
        return max(0, self.level.target_minutes - self.filled_minutes)


@dataclass
class OverallProgress:
    language: Language
    goal_level: Level | None
    total_minutes: int
    goal_minutes: int
    levels: list[LevelProgress]
    overflow_minutes: int = 0

    @property
    def total_pct(self) -> float:
        if self.goal_minutes <= 0:
            return 0.0
        return min(100.0, self.total_minutes / self.goal_minutes * 100)

    @property
    def current_level(self) -> LevelProgress | None:
        for lp in self.levels:
            if lp.status == "current":
                return lp
        return None

    @property
    def is_goal_reached(self) -> bool:
        return self.total_minutes >= self.goal_minutes > 0


def _ordered_levels_to_goal(language: Language) -> list[Level]:
    levels = sorted(language.levels, key=lambda lv: lv.sort_order)
    if language.goal_level_id is None:
        return levels
    out = []
    for lv in levels:
        out.append(lv)
        if lv.id == language.goal_level_id:
            break
    return out


def compute_overall_progress(language: Language) -> OverallProgress:
    """Fill levels in order like water into stacked glasses (PLAN.md §6.2),
    then attribute each session's minutes to whichever level was "current"
    at the moment it was logged, splitting a session across a level boundary
    proportionally so per-skill mini-bars (§6.3) stay accurate.
    """
    levels = _ordered_levels_to_goal(language)
    goal_minutes = sum(lv.target_minutes for lv in levels)

    sessions: list[StudySession] = (
        StudySession.query.filter_by(language_id=language.id)
        .order_by(StudySession.study_date.asc(), StudySession.id.asc())
        .all()
    )
    total_minutes = sum(s.minutes for s in sessions)

    level_progress = [LevelProgress(level=lv) for lv in levels]
    for lp in level_progress:
        for st in lp.level.skill_targets:
            target = int(round(lp.level.target_minutes * float(st.percent) / 100))
            lp.skills[st.activity_type_id] = SkillProgress(
                activity_type=st.activity_type, target_minutes=target
            )

    idx = 0
    for session in sessions:
        remaining = session.minutes
        while remaining > 0 and idx < len(level_progress):
            lp = level_progress[idx]
            space = lp.level.target_minutes - lp.filled_minutes
            if space <= 0:
                idx += 1
                continue
            take = min(space, remaining)
            lp.filled_minutes += take
            skill = lp.skills.get(session.activity_type_id)
            if skill is not None:
                skill.earned_minutes += take
            remaining -= take
            if lp.filled_minutes >= lp.level.target_minutes:
                idx += 1
        # anything left over (idx exhausted all levels) is overflow, added below

    overflow_minutes = max(0, total_minutes - goal_minutes)

    found_current = False
    for lp in level_progress:
        if lp.filled_minutes >= lp.level.target_minutes and lp.level.target_minutes > 0:
            lp.status = "done"
        elif not found_current:
            lp.status = "current"
            found_current = True
        else:
            lp.status = "locked"
    # Edge case: all levels done (goal already reached) -> no "current"; that's fine,
    # the template shows the "goal reached" state instead.

    return OverallProgress(
        language=language,
        goal_level=language.goal_level,
        total_minutes=total_minutes,
        goal_minutes=goal_minutes,
        levels=level_progress,
        overflow_minutes=overflow_minutes,
    )


MARK_COMPLETE_NOTE = "Marked complete (hours estimated, not logged session by session)"


def mark_level_complete(language: Language, level: Level, *, on: date | None = None) -> int:
    """Log catch-up study sessions so the learner's total reaches the end of
    `level`, for when they know they've finished a level but don't remember
    the exact hours. Distributes the shortfall across the level's skill-mix
    percentages (so its per-skill mini-bars read as complete too), split into
    multiple same-day sessions to respect the 960-minute-per-session cap.
    Returns the number of minutes added (0 if the level was already reached).
    These are ordinary StudySession rows -- editable/deletable from the Log
    page like any other entry, tagged with `MARK_COMPLETE_NOTE` so they're
    easy to spot.
    """
    progress = compute_overall_progress(language)
    levels = _ordered_levels_to_goal(language)
    cumulative_target = sum(lv.target_minutes for lv in levels if lv.sort_order <= level.sort_order)
    shortfall = cumulative_target - progress.total_minutes
    if shortfall <= 0:
        return 0

    study_date = on or today_local()
    skill_targets = list(level.skill_targets)
    allocations: list[tuple[int, int]] = []  # (activity_type_id, minutes)
    if skill_targets:
        remaining = shortfall
        for i, st in enumerate(skill_targets):
            if i == len(skill_targets) - 1:
                minutes = remaining  # last bucket absorbs any rounding leftover
            else:
                minutes = round(shortfall * float(st.percent) / 100)
                remaining -= minutes
            if minutes > 0:
                allocations.append((st.activity_type_id, minutes))
    else:
        fallback = (
            ActivityType.query.filter_by(is_archived=False)
            .order_by(ActivityType.sort_order)
            .first()
        )
        if fallback:
            allocations.append((fallback.id, shortfall))

    for activity_type_id, minutes in allocations:
        remaining = minutes
        while remaining > 0:
            chunk = min(remaining, 960)
            db.session.add(
                StudySession(
                    user_id=language.user_id,
                    language_id=language.id,
                    activity_type_id=activity_type_id,
                    study_date=study_date,
                    minutes=chunk,
                    note=MARK_COMPLETE_NOTE,
                    is_backfill=True,
                )
            )
            remaining -= chunk
    db.session.commit()
    return shortfall


@dataclass
class Eta:
    pace_minutes_per_day: float
    next_level_date: date | None
    goal_date: date | None


def compute_eta(language: Language, progress: OverallProgress, *, window_days: int = 28) -> Eta:
    """Project dates for the current level and the goal level from recent pace.
    Falls back to all-time average if there isn't `window_days` of history yet.
    Returns None dates when pace is 0 (nothing to divide by). Backfilled
    "mark level complete" catch-up entries are excluded from the pace
    calculation -- a one-off lump of hours isn't a sustainable daily rate and
    would otherwise make the projection wildly (and wrongly) optimistic.
    """
    today = today_local()
    window_start = today - timedelta(days=window_days - 1)

    recent_minutes = (
        db.session.query(db.func.coalesce(db.func.sum(StudySession.minutes), 0))
        .filter(
            StudySession.language_id == language.id,
            StudySession.study_date >= window_start,
            StudySession.study_date <= today,
            StudySession.is_backfill.is_(False),
        )
        .scalar()
    )

    first_session_date = (
        db.session.query(db.func.min(StudySession.study_date))
        .filter(StudySession.language_id == language.id, StudySession.is_backfill.is_(False))
        .scalar()
    )

    if first_session_date is not None and first_session_date > window_start:
        days_of_history = (today - first_session_date).days + 1
        pace = recent_minutes / days_of_history if days_of_history > 0 else 0.0
    else:
        pace = recent_minutes / window_days

    if pace <= 0:
        return Eta(pace_minutes_per_day=0.0, next_level_date=None, goal_date=None)

    current = progress.current_level
    next_level_date = None
    if current is not None and current.remaining_minutes > 0:
        days_needed = _ceil_div(current.remaining_minutes, pace)
        next_level_date = today + timedelta(days=days_needed)

    goal_remaining = max(0, progress.goal_minutes - progress.total_minutes)
    goal_date = None
    if goal_remaining > 0:
        days_needed = _ceil_div(goal_remaining, pace)
        goal_date = today + timedelta(days=days_needed)

    return Eta(pace_minutes_per_day=pace, next_level_date=next_level_date, goal_date=goal_date)


def _ceil_div(minutes: float, per_day: float) -> int:
    import math

    return max(0, math.ceil(minutes / per_day))


def what_if_dates(progress: OverallProgress, minutes_per_day: float) -> Eta:
    """Same as compute_eta but with a hypothetical, user-chosen pace (used by
    the Stats page's what-if slider, computed client-side normally, but this
    is available server-side too / for tests)."""
    today = today_local()
    if minutes_per_day <= 0:
        return Eta(pace_minutes_per_day=0.0, next_level_date=None, goal_date=None)

    current = progress.current_level
    next_level_date = None
    if current is not None and current.remaining_minutes > 0:
        next_level_date = today + timedelta(
            days=_ceil_div(current.remaining_minutes, minutes_per_day)
        )

    goal_remaining = max(0, progress.goal_minutes - progress.total_minutes)
    goal_date = None
    if goal_remaining > 0:
        goal_date = today + timedelta(days=_ceil_div(goal_remaining, minutes_per_day))

    return Eta(
        pace_minutes_per_day=minutes_per_day, next_level_date=next_level_date, goal_date=goal_date
    )
