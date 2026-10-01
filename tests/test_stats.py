from __future__ import annotations

from datetime import date

import time_machine

from sprachweg.extensions import db
from sprachweg.models import ActivityType, StudySession
from sprachweg.services.stats import activity_split_all_time, weekly_breakdown


def _log(
    language, minutes: int, on: date, *, activity_key: str = "vocab", is_backfill: bool = False
) -> None:
    activity = ActivityType.query.filter_by(key=activity_key).first()
    db.session.add(
        StudySession(
            user_id=language.user_id,
            language_id=language.id,
            activity_type_id=activity.id,
            study_date=on,
            minutes=minutes,
            is_backfill=is_backfill,
        )
    )
    db.session.commit()


def test_weekly_breakdown_excludes_backfill_entries(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        _log(language, 30, date(2027, 1, 15))
        _log(language, 900, date(2027, 1, 15), is_backfill=True)
        weekly = weekly_breakdown(language.id, weeks=4)

    this_week = weekly[-1]
    assert this_week.total_minutes == 30
    assert this_week.by_activity.get("vocab") == 30


def test_activity_split_all_time_excludes_backfill_entries(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        _log(language, 30, date(2027, 1, 15))
        _log(language, 900, date(2027, 1, 15), is_backfill=True)
        split = activity_split_all_time(language.id)

    assert split.get("vocab") == 30
