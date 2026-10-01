"""Streak & consistency calculations. See PLAN.md §6.4 for the spec and the
required test matrix (empty DB, today-empty, gaps, month/year boundaries,
below-threshold days, DST weeks) — all covered in tests/test_streaks.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sprachweg.extensions import db
from sprachweg.models import PlanItem, PlanItemStatus, StudySession, today_local


@dataclass
class StreakStats:
    current_streak: int
    longest_streak: int
    longest_streak_start: date | None
    longest_streak_end: date | None
    total_active_days: int
    active_days_this_month: int
    days_this_month_so_far: int
    is_today_active: bool
    at_risk: bool  # streak alive but today not yet logged
    best_day_minutes: int
    best_day_date: date | None
    avg_minutes_per_active_day: float
    avg_minutes_last_30d: float


def _daily_totals(
    user_id: int, language_id: int | None, *, exclude_backfill: bool = False
) -> dict[date, int]:
    query = db.session.query(StudySession.study_date, db.func.sum(StudySession.minutes)).filter(
        StudySession.user_id == user_id
    )
    if language_id is not None:
        query = query.filter(StudySession.language_id == language_id)
    if exclude_backfill:
        query = query.filter(StudySession.is_backfill.is_(False))
    rows = query.group_by(StudySession.study_date).all()
    return {d: int(m) for d, m in rows}


def compute_streaks(
    user_id: int, language_id: int | None = None, *, threshold: int = 10
) -> StreakStats:
    """Streak stats for `user_id`. `language_id=None` aggregates across all
    of that user's languages (used for an 'all languages' overview and the
    public profile/leaderboard); pass a specific id for a per-language view.
    `threshold` is the user's `streak_min_minutes` setting -- passed in
    explicitly so this stays a pure, easily-unit-tested function.
    """
    # `totals` (incl. backfill) decides which days count toward the streak --
    # a "mark level complete" catch-up still represents a real action that
    # day. `real_totals` (excl. backfill) drives magnitude stats (best day,
    # averages) so one lump catch-up entry doesn't masquerade as your best
    # day ever or inflate your daily average.
    totals = _daily_totals(user_id, language_id)
    real_totals = _daily_totals(user_id, language_id, exclude_backfill=True)
    active_dates = {d for d, m in totals.items() if m >= threshold}
    today = today_local()

    if not active_dates:
        return StreakStats(
            current_streak=0,
            longest_streak=0,
            longest_streak_start=None,
            longest_streak_end=None,
            total_active_days=0,
            active_days_this_month=0,
            days_this_month_so_far=today.day,
            is_today_active=False,
            at_risk=False,
            best_day_minutes=0,
            best_day_date=None,
            avg_minutes_per_active_day=0.0,
            avg_minutes_last_30d=0.0,
        )

    is_today_active = today in active_dates

    # Current streak: consecutive active days ending today, or ending
    # yesterday if today isn't active yet ("at risk" rather than broken).
    anchor = today if is_today_active else today - timedelta(days=1)
    current_streak = 0
    cursor = anchor
    while cursor in active_dates:
        current_streak += 1
        cursor -= timedelta(days=1)
    at_risk = current_streak > 0 and not is_today_active

    # Longest streak ever: scan sorted dates for the longest consecutive run.
    sorted_dates = sorted(active_dates)
    longest_streak = 0
    longest_start = longest_end = None
    run_start = sorted_dates[0]
    run_len = 1
    for prev, curr in zip(sorted_dates, sorted_dates[1:], strict=False):
        if curr - prev == timedelta(days=1):
            run_len += 1
        else:
            if run_len > longest_streak:
                longest_streak = run_len
                longest_start, longest_end = run_start, prev
            run_start = curr
            run_len = 1
    if run_len > longest_streak:
        longest_streak = run_len
        longest_start, longest_end = run_start, sorted_dates[-1]

    total_active_days = len(active_dates)
    month_start = today.replace(day=1)
    active_days_this_month = sum(1 for d in active_dates if d >= month_start and d <= today)

    if real_totals:
        best_day_date = max(real_totals, key=lambda d: real_totals[d])
        best_day_minutes = real_totals[best_day_date]
    else:
        best_day_date = None
        best_day_minutes = 0

    avg_per_active_day = (
        sum(real_totals.get(d, 0) for d in active_dates) / total_active_days
        if total_active_days
        else 0.0
    )

    last_30_start = today - timedelta(days=29)
    last_30_total = sum(m for d, m in real_totals.items() if last_30_start <= d <= today)
    avg_last_30 = last_30_total / 30

    return StreakStats(
        current_streak=current_streak,
        longest_streak=longest_streak,
        longest_streak_start=longest_start,
        longest_streak_end=longest_end,
        total_active_days=total_active_days,
        active_days_this_month=active_days_this_month,
        days_this_month_so_far=today.day,
        is_today_active=is_today_active,
        at_risk=at_risk,
        best_day_minutes=best_day_minutes,
        best_day_date=best_day_date,
        avg_minutes_per_active_day=avg_per_active_day,
        avg_minutes_last_30d=avg_last_30,
    )


def compute_plan_adherence(language_id: int, *, days: int = 7) -> float | None:
    """(done + 0.5*partial) / planned items over the trailing window.
    Returns None if there were no planned items in that window (nothing to
    divide by — the UI should show "no plan" rather than 0%).
    """
    today = today_local()
    start = today - timedelta(days=days - 1)
    items = (
        PlanItem.query.join(PlanItem.plan)
        .filter(
            PlanItem.date >= start,
            PlanItem.date <= today,
        )
        .filter(PlanItem.plan.has(language_id=language_id))
        .all()
    )
    if not items:
        return None
    score = 0.0
    for item in items:
        if item.status == PlanItemStatus.DONE:
            score += 1.0
        elif item.status == PlanItemStatus.PARTIAL:
            score += 0.5
    return round(score / len(items) * 100, 1)
