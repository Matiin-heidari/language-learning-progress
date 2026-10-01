from __future__ import annotations

from datetime import date, timedelta

import time_machine

from sprachweg.extensions import db
from sprachweg.models import ActivityType, Level, StudySession
from sprachweg.services.progress import (
    MARK_COMPLETE_NOTE,
    compute_eta,
    compute_overall_progress,
    mark_level_complete,
)


def _log(language, minutes: int, on: date, activity_key: str = "vocab") -> None:
    """Log `minutes` total on `on`, split into <=960-minute rows (the model's
    per-session cap) since tests often need more than a day's worth at once."""
    activity = ActivityType.query.filter_by(key=activity_key).first()
    remaining = minutes
    while remaining > 0:
        chunk = min(remaining, 960)
        db.session.add(
            StudySession(
                user_id=language.user_id,
                language_id=language.id,
                activity_type_id=activity.id,
                study_date=on,
                minutes=chunk,
            )
        )
        remaining -= chunk
    db.session.commit()


def test_zero_hours_progress(app, language):
    progress = compute_overall_progress(language)
    assert progress.total_minutes == 0
    assert progress.total_pct == 0
    assert progress.current_level.level.code == "A1"
    assert all(lp.status in ("current", "locked") for lp in progress.levels)


def test_hours_fill_levels_in_order(app, language):
    # A1 target is 120h = 7200 minutes. Log exactly that plus 60 more minutes,
    # which should spill over fully into A2.
    _log(language, 7200, date(2027, 1, 1))
    _log(language, 60, date(2027, 1, 2))
    progress = compute_overall_progress(language)

    a1 = next(lp for lp in progress.levels if lp.level.code == "A1")
    a2 = next(lp for lp in progress.levels if lp.level.code == "A2")

    assert a1.status == "done"
    assert a1.filled_minutes == 7200
    assert a1.pct == 100
    assert a2.status == "current"
    assert a2.filled_minutes == 60


def test_exact_level_boundary_marks_level_done_not_overflowing_next(app, language):
    _log(language, 7200, date(2027, 1, 1))  # exactly A1's target, nothing more
    progress = compute_overall_progress(language)
    a1 = next(lp for lp in progress.levels if lp.level.code == "A1")
    a2 = next(lp for lp in progress.levels if lp.level.code == "A2")
    assert a1.status == "done"
    assert a2.status == "current"
    assert a2.filled_minutes == 0


def test_overflow_beyond_goal_level_is_tracked_separately(app, language):
    # Push far more minutes than the entire A1-C1 goal (1200h = 72000 min).
    _log(language, 80000, date(2027, 1, 1))
    progress = compute_overall_progress(language)
    assert progress.is_goal_reached is True
    assert progress.overflow_minutes == 80000 - progress.goal_minutes
    assert progress.current_level is None  # every level is done


def test_editing_a_level_target_only_affects_that_level(app, language, db):
    from sprachweg.models import Level

    a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
    a1.target_hours = 50
    db.session.commit()

    _log(language, 3100, date(2027, 1, 1))  # 51.67h -> should fill A1 (50h) then spill to A2
    progress = compute_overall_progress(language)
    a1p = next(lp for lp in progress.levels if lp.level.code == "A1")
    a2p = next(lp for lp in progress.levels if lp.level.code == "A2")
    assert a1p.status == "done"
    assert a1p.level.target_minutes == 3000
    assert a2p.filled_minutes == 100


def test_per_skill_split_across_level_boundary(app, language):
    # Fill A1 (120h) entirely with vocab (a skewed, vocab-only mix), then log
    # 10 more minutes of vocab which should land in A2's vocab bucket instead.
    _log(language, 7200, date(2027, 1, 1), "vocab")
    _log(language, 10, date(2027, 1, 2), "vocab")
    progress = compute_overall_progress(language)
    a1 = next(lp for lp in progress.levels if lp.level.code == "A1")
    a2 = next(lp for lp in progress.levels if lp.level.code == "A2")

    vocab_activity = ActivityType.query.filter_by(key="vocab").first()
    a1_vocab = a1.skills[vocab_activity.id]
    a2_vocab = a2.skills[vocab_activity.id]

    # A1's overall 120h cap was reached purely with vocab: earned_minutes can
    # exceed that skill's own sub-target (30h = 25% of 120h) -- the mini-bar's
    # displayed *percentage* is what caps at 100%, not the raw minutes.
    assert a1_vocab.target_minutes == 1800  # 25% of A1's 120h
    assert a1_vocab.earned_minutes == 7200
    assert a1_vocab.pct == 100.0

    # Minutes logged after A1 is full correctly spill into A2's vocab bucket.
    assert a2_vocab.earned_minutes == 10


def test_eta_hidden_when_pace_is_zero(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        progress = compute_overall_progress(language)
        eta = compute_eta(language, progress)
    assert eta.pace_minutes_per_day == 0.0
    assert eta.goal_date is None
    assert eta.next_level_date is None


def test_eta_projects_a_future_date_from_recent_pace(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        for i in range(28):
            _log(language, 60, date(2027, 1, 15) - timedelta(days=i))
        progress = compute_overall_progress(language)
        eta = compute_eta(language, progress)
    assert eta.pace_minutes_per_day == 60.0
    assert eta.goal_date is not None
    assert eta.next_level_date is not None


def test_mark_level_complete_fills_the_shortfall_from_scratch(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
        added = mark_level_complete(language, a1)
        progress = compute_overall_progress(language)

    assert added == a1.target_minutes  # 120h = 7200 min, nothing logged yet
    a1p = next(lp for lp in progress.levels if lp.level.code == "A1")
    assert a1p.status == "done"
    assert a1p.filled_minutes == a1.target_minutes


def test_mark_level_complete_only_fills_the_remaining_shortfall(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
        _log(language, 1800, date(2027, 1, 1))  # already logged 30h of A1's 120h
        added = mark_level_complete(language, a1)

    assert added == a1.target_minutes - 1800


def test_mark_level_complete_is_a_noop_if_already_done(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
        mark_level_complete(language, a1)
        added_again = mark_level_complete(language, a1)

    assert added_again == 0


def test_mark_level_complete_respects_per_session_minute_cap(app, language):
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
        mark_level_complete(language, a1)
        sessions = StudySession.query.filter_by(language_id=language.id).all()

    assert all(s.minutes <= 960 for s in sessions)
    assert sum(s.minutes for s in sessions) == a1.target_minutes
    assert all(s.note == MARK_COMPLETE_NOTE for s in sessions)
    assert all(s.is_backfill for s in sessions)


def test_mark_level_complete_is_editable_and_deletable_afterward(app, language, db):
    # The catch-up entries are ordinary sessions: deleting them undoes the
    # "mark complete" action, just like fixing a mistaken manual log entry.
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
        mark_level_complete(language, a1)
        StudySession.query.filter_by(language_id=language.id).delete()
        db.session.commit()
        progress = compute_overall_progress(language)

    a1p = next(lp for lp in progress.levels if lp.level.code == "A1")
    assert a1p.filled_minutes == 0
    assert a1p.status == "current"


def test_eta_pace_excludes_backfill_catchup_minutes(app, language):
    # A real day of study plus a "mark level complete" lump on the same day:
    # the lump shouldn't inflate the projected pace to something unrealistic.
    with time_machine.travel("2027-01-15 12:00:00+00:00"):
        _log(language, 30, date(2027, 1, 15))  # one real day, 30 min
        a1 = Level.query.filter_by(language_id=language.id, code="A1").first()
        mark_level_complete(language, a1)  # adds a 7200-minute backfill lump
        progress = compute_overall_progress(language)
        eta = compute_eta(language, progress)

    # Pace should reflect only the 30 real minutes over 1 day of real history,
    # not the 7200-minute backfill lump landing on the same day (which would
    # otherwise make the pace -- and the projected ETA -- absurdly optimistic).
    assert eta.pace_minutes_per_day == 30.0
