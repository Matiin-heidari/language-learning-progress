"""GitHub-style activity heatmap grid builder. See PLAN.md §6.7.

Produces a week-major grid (list of weeks, each a list of 7 day-cells) that
the Jinja macro renders as SVG. Weeks start Monday or Sunday per the
`week_start` setting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sprachweg.extensions import db
from sprachweg.models import StudySession, today_local

# (upper bound minutes inclusive, level) — level 0 is "0 minutes"
_BUCKETS = [(0, 0), (14, 1), (29, 2), (59, 3), (119, 4)]  # anything above -> level 5


def _bucket(minutes: int) -> int:
    if minutes <= 0:
        return 0
    for upper, level in _BUCKETS:
        if minutes <= upper:
            return level
    return 5


@dataclass
class DayCell:
    date: date
    minutes: int
    level: int
    is_future: bool
    is_today: bool
    is_in_range: bool  # False for padding cells before day 1 of the grid


@dataclass
class HeatmapGrid:
    weeks: list[list[DayCell]]
    # (week index, short month name) for the first week each month appears in
    month_labels: list[tuple[int, str]]
    total_active_days: int
    total_minutes: int
    start: date
    end: date


def build_heatmap(
    user_id: int,
    language_id: int | None = None,
    *,
    end: date | None = None,
    days: int = 365,
    week_start: str = "mon",
) -> HeatmapGrid:
    """Heatmap for `user_id`. `language_id=None` aggregates across all of
    that user's languages (profile page); pass a specific id for a
    per-language view. `week_start` is the user's `week_start` setting,
    passed in explicitly so this stays a pure, easily-unit-tested function.
    """
    today = today_local()
    end = end or today
    start = end - timedelta(days=days - 1)

    week_start_weekday = 6 if week_start == "sun" else 0  # Python: Mon=0..Sun=6

    # Pad the grid start back to the beginning of its week so columns align.
    offset = (start.weekday() - week_start_weekday) % 7
    grid_start = start - timedelta(days=offset)
    # Pad the end forward to the end of its week.
    offset_end = (week_start_weekday - 1 - end.weekday()) % 7
    grid_end = end + timedelta(days=offset_end)

    query = db.session.query(StudySession.study_date, db.func.sum(StudySession.minutes)).filter(
        StudySession.user_id == user_id,
        StudySession.study_date >= grid_start,
        StudySession.study_date <= grid_end,
    )
    if language_id is not None:
        query = query.filter(StudySession.language_id == language_id)
    totals = {d: int(m) for d, m in query.group_by(StudySession.study_date).all()}

    weeks: list[list[DayCell]] = []
    month_labels: list[tuple[int, str]] = []
    seen_months: set[tuple[int, int]] = set()

    cursor = grid_start
    week: list[DayCell] = []
    week_index = 0
    while cursor <= grid_end:
        minutes = totals.get(cursor, 0)
        in_range = start <= cursor <= end
        cell = DayCell(
            date=cursor,
            minutes=minutes if in_range else 0,
            level=_bucket(minutes) if in_range else 0,
            is_future=cursor > today,
            is_today=cursor == today,
            is_in_range=in_range,
        )
        week.append(cell)

        month_key = (cursor.year, cursor.month)
        if in_range and cursor.day <= 7 and month_key not in seen_months:
            seen_months.add(month_key)
            month_labels.append((week_index, cursor.strftime("%b")))

        if len(week) == 7:
            weeks.append(week)
            week = []
            week_index += 1
        cursor += timedelta(days=1)
    if week:
        weeks.append(week)

    total_active_days = sum(1 for d, m in totals.items() if start <= d <= end and m > 0)
    total_minutes = sum(m for d, m in totals.items() if start <= d <= end)

    return HeatmapGrid(
        weeks=weeks,
        month_labels=month_labels,
        total_active_days=total_active_days,
        total_minutes=total_minutes,
        start=start,
        end=end,
    )
