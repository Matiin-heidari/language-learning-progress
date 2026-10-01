"""Aggregate stats for the /stats page and its Chart.js data endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sprachweg.extensions import db
from sprachweg.models import ActivityType, StudySession, today_local


@dataclass
class WeekBucket:
    week_start: str  # ISO date
    label: str
    by_activity: dict[str, int]  # activity key -> minutes
    total_minutes: int


def weekly_breakdown(language_id: int, *, weeks: int = 12) -> list[WeekBucket]:
    """Last `weeks` ISO weeks (Mon-Sun), each broken down by activity, oldest
    first — ready for a stacked bar chart. Excludes "mark level complete"
    catch-up entries (`is_backfill`): a one-off lump of backfilled hours would
    dwarf every real day on the same y-axis scale (it still counts toward
    total/level progress, just not this rate-of-study chart).
    """
    today = today_local()
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(weeks=weeks - 1)

    rows = (
        db.session.query(
            StudySession.study_date, ActivityType.key, db.func.sum(StudySession.minutes)
        )
        .join(ActivityType, StudySession.activity_type_id == ActivityType.id)
        .filter(
            StudySession.language_id == language_id,
            StudySession.study_date >= start,
            StudySession.is_backfill.is_(False),
        )
        .group_by(StudySession.study_date, ActivityType.key)
        .all()
    )

    buckets: dict[int, WeekBucket] = {}
    for i in range(weeks):
        week_start = start + timedelta(weeks=i)
        buckets[i] = WeekBucket(
            week_start=week_start.isoformat(),
            label=week_start.strftime("%d %b"),
            by_activity={},
            total_minutes=0,
        )

    for study_date, activity_key, minutes in rows:
        week_index = (study_date - start).days // 7
        if week_index not in buckets:
            continue
        bucket = buckets[week_index]
        bucket.by_activity[activity_key] = bucket.by_activity.get(activity_key, 0) + int(minutes)
        bucket.total_minutes += int(minutes)

    return [buckets[i] for i in range(weeks)]


def activity_split_all_time(language_id: int) -> dict[str, int]:
    """All-time minutes per activity, excluding backfill catch-up entries --
    same reasoning as `weekly_breakdown`."""
    rows = (
        db.session.query(ActivityType.key, db.func.sum(StudySession.minutes))
        .join(ActivityType, StudySession.activity_type_id == ActivityType.id)
        .filter(
            StudySession.language_id == language_id,
            StudySession.is_backfill.is_(False),
        )
        .group_by(ActivityType.key)
        .all()
    )
    return {key: int(minutes) for key, minutes in rows}
