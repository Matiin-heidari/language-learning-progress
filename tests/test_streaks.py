from __future__ import annotations

from datetime import date, timedelta

import time_machine

from sprachweg.extensions import db
from sprachweg.models import ActivityType, StudySession
from sprachweg.services.streaks import compute_streaks

FROZEN_NOON_UTC = "2027-01-15 12:00:00+00:00"  # noon UTC avoids local-midnight edge cases


def _log(language, minutes: int, on: date, activity_key: str = "vocab") -> None:
    activity = ActivityType.query.filter_by(key=activity_key).first()
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


def test_empty_db_has_no_streak(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 0
    assert stats.longest_streak == 0
    assert stats.total_active_days == 0
    assert stats.at_risk is False
    assert stats.is_today_active is False


def test_single_session_today_counts_as_streak_of_one(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        today = date(2027, 1, 15)
        _log(language, 30, today)
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 1
    assert stats.longest_streak == 1
    assert stats.is_today_active is True
    assert stats.at_risk is False


def test_session_only_yesterday_is_at_risk_not_broken(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        yesterday = date(2027, 1, 14)
        _log(language, 30, yesterday)
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 1
    assert stats.at_risk is True
    assert stats.is_today_active is False


def test_streak_broken_two_days_ago_is_zero_current(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        two_days_ago = date(2027, 1, 13)
        _log(language, 30, two_days_ago)
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 0
    assert stats.longest_streak == 1


def test_day_below_threshold_does_not_count_as_active(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        today = date(2027, 1, 15)
        _log(language, 5, today)  # default threshold is 10 minutes
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 0
    assert stats.is_today_active is False


def test_multiple_sessions_same_day_are_summed_for_threshold(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        today = date(2027, 1, 15)
        _log(language, 5, today, "vocab")
        _log(language, 5, today, "grammar")
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 1
    assert stats.is_today_active is True


def test_longest_streak_can_exceed_current_streak(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        today = date(2027, 1, 15)
        # a 5-day streak in the past, then a gap, then a single active day today
        for i in range(10, 15):
            _log(language, 30, date(2027, 1, 1) + timedelta(days=i - 10))
        _log(language, 30, today)
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 1
    assert stats.longest_streak == 5


def test_streak_spans_month_and_year_boundary(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        for d in [date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2)]:
            _log(language, 30, d)
        stats = compute_streaks(language.user_id, language.id)
    assert stats.longest_streak == 4


def test_streak_survives_dst_boundary_week(app, language):
    # Europe/Berlin springs forward on the last Sunday of March; date-only
    # arithmetic must not skip or double-count a day across that week.
    with time_machine.travel("2027-03-30 12:00:00+00:00"):
        for offset in range(6):
            _log(language, 30, date(2027, 3, 25) + timedelta(days=offset))
        stats = compute_streaks(language.user_id, language.id)
    assert stats.current_streak == 6
    assert stats.longest_streak == 6


def test_best_day_and_averages(app, language):
    with time_machine.travel(FROZEN_NOON_UTC):
        _log(language, 20, date(2027, 1, 14))
        _log(language, 90, date(2027, 1, 15))
        stats = compute_streaks(language.user_id, language.id)
    assert stats.best_day_minutes == 90
    assert stats.best_day_date == date(2027, 1, 15)
    assert stats.total_active_days == 2


def test_backfill_day_counts_as_active_but_not_as_best_day(app, language):
    # A "mark level complete" catch-up day should keep the streak alive
    # (it's a real action that day) but shouldn't crown it "best day ever"
    # or inflate the daily average -- that's for real logged study time.
    with time_machine.travel(FROZEN_NOON_UTC):
        _log(language, 20, date(2027, 1, 14))  # one real day
        activity = ActivityType.query.filter_by(key="vocab").first()
        db.session.add(
            StudySession(
                user_id=language.user_id,
                language_id=language.id,
                activity_type_id=activity.id,
                study_date=date(2027, 1, 15),
                minutes=900,
                is_backfill=True,
            )
        )
        db.session.commit()
        stats = compute_streaks(language.user_id, language.id)

    assert stats.is_today_active is True  # backfill day still counts as active
    assert stats.current_streak == 2  # 14th + 15th, consecutive
    assert stats.best_day_minutes == 20  # not the 900-minute backfill day
    assert stats.best_day_date == date(2027, 1, 14)
