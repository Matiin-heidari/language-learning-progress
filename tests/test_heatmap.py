from __future__ import annotations

from datetime import date

import time_machine

from sprachweg.extensions import db
from sprachweg.models import ActivityType, StudySession
from sprachweg.services.heatmap import build_heatmap


def _log(language, minutes: int, on: date) -> None:
    activity = ActivityType.query.filter_by(key="vocab").first()
    db.session.add(
        StudySession(
            user_id=language.user_id,
            language_id=language.id,
            activity_type_id=activity.id,
            study_date=on,
            minutes=minutes,
        )
    )
    db.session.commit()


def test_grid_has_seven_rows_per_week_and_full_weeks_only(app, language):
    with time_machine.travel("2027-06-15 12:00:00+00:00"):
        grid = build_heatmap(language.user_id, language.id, days=365)
    assert all(len(week) == 7 for week in grid.weeks)
    # 365 days padded out to whole weeks means somewhere around 53-54 weeks
    assert 53 <= len(grid.weeks) <= 54


def test_monday_start_aligns_first_column_to_monday(app, language):
    with time_machine.travel("2027-06-15 12:00:00+00:00"):
        grid = build_heatmap(language.user_id, language.id, days=365, week_start="mon")
    assert grid.weeks[0][0].date.weekday() == 0  # Monday
    assert grid.weeks[0][6].date.weekday() == 6  # Sunday


def test_sunday_start_aligns_first_column_to_sunday(app, language):
    with time_machine.travel("2027-06-15 12:00:00+00:00"):
        grid = build_heatmap(language.user_id, language.id, days=365, week_start="sun")
    assert grid.weeks[0][0].date.weekday() == 6  # Sunday
    assert grid.weeks[0][6].date.weekday() == 5  # Saturday


def test_out_of_range_padding_cells_are_not_counted(app, language):
    with time_machine.travel("2027-06-15 12:00:00+00:00"):
        grid = build_heatmap(language.user_id, language.id, days=365)
    padding_cells = [d for week in grid.weeks for d in week if not d.is_in_range]
    assert all(c.minutes == 0 and c.level == 0 for c in padding_cells)


def test_today_cell_is_flagged(app, language):
    with time_machine.travel("2027-06-15 12:00:00+00:00"):
        grid = build_heatmap(language.user_id, language.id, days=365)
    today_cells = [d for week in grid.weeks for d in week if d.is_today]
    assert len(today_cells) == 1
    assert today_cells[0].date == date(2027, 6, 15)


def test_minutes_bucket_thresholds(app, language):
    with time_machine.travel("2027-06-15 12:00:00+00:00"):
        _log(language, 45, date(2027, 6, 10))
        _log(language, 120, date(2027, 6, 11))
        grid = build_heatmap(language.user_id, language.id, days=365)
    cells_by_date = {d.date: d for week in grid.weeks for d in week}
    assert cells_by_date[date(2027, 6, 10)].level == 3  # 30-59 min bucket
    assert cells_by_date[date(2027, 6, 11)].level == 5  # >=120 min bucket
