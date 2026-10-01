"""Cross-user aggregates for the leaderboard and public profile pages.
Only `User.is_public` accounts are ever ranked or shown to others.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sprachweg.extensions import db
from sprachweg.models import StudySession, User, today_local
from sprachweg.services.streaks import compute_streaks


@dataclass
class LeaderboardRow:
    rank: int
    user: User
    value: float  # minutes for the "today"/"week" metrics, days for "streak"


def _minutes_leaderboard(*, start, end, limit: int) -> list[LeaderboardRow]:
    rows = (
        db.session.query(StudySession.user_id, db.func.sum(StudySession.minutes))
        .join(User, StudySession.user_id == User.id)
        .filter(
            User.is_public.is_(True),
            StudySession.study_date >= start,
            StudySession.study_date <= end,
            StudySession.is_backfill.is_(False),
        )
        .group_by(StudySession.user_id)
        .order_by(db.func.sum(StudySession.minutes).desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return []
    users_by_id = {u.id: u for u in User.query.filter(User.id.in_([r[0] for r in rows])).all()}
    return [
        LeaderboardRow(rank=i + 1, user=users_by_id[user_id], value=float(minutes))
        for i, (user_id, minutes) in enumerate(rows)
        if user_id in users_by_id
    ]


def today_leaderboard(*, limit: int = 50) -> list[LeaderboardRow]:
    today = today_local()
    return _minutes_leaderboard(start=today, end=today, limit=limit)


def week_leaderboard(*, limit: int = 50) -> list[LeaderboardRow]:
    today = today_local()
    week_start = today - timedelta(days=today.weekday())
    return _minutes_leaderboard(start=week_start, end=today, limit=limit)


def streak_leaderboard(*, limit: int = 50) -> list[LeaderboardRow]:
    """Ranked by current streak. There's no cheap SQL GROUP BY for "longest
    consecutive run", so this re-uses `compute_streaks` per public user --
    fine at the scale this app runs at (a personal/small-group tracker).
    """
    rows = []
    for user in User.query.filter_by(is_public=True).all():
        stats = compute_streaks(user.id, threshold=user.streak_min_minutes)
        if stats.current_streak > 0:
            rows.append((user, stats.current_streak))
    rows.sort(key=lambda r: r[1], reverse=True)
    return [
        LeaderboardRow(rank=i + 1, user=user, value=float(streak))
        for i, (user, streak) in enumerate(rows[:limit])
    ]
