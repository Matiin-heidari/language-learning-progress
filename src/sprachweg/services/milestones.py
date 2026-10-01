"""Detects newly-reached milestones after a session is logged, records them
(so they fire exactly once), and returns the ones worth celebrating right now.
See PLAN.md §7.5.
"""

from __future__ import annotations

from dataclasses import dataclass

from sprachweg.extensions import db
from sprachweg.models import Language, MilestoneEvent, today_local
from sprachweg.services.progress import compute_overall_progress
from sprachweg.services.streaks import compute_streaks

STREAK_MILESTONES = [7, 14, 30, 50, 100, 200, 365]
HOURS_MILESTONES = [10, 25, 50, 100, 250, 500, 750, 1000]


@dataclass
class NewMilestone:
    kind: str
    ref: str
    label: str


def _record_if_new(language_id: int, kind: str, ref: str) -> bool:
    exists = MilestoneEvent.query.filter_by(language_id=language_id, kind=kind, ref=ref).first()
    if exists:
        return False
    db.session.add(
        MilestoneEvent(
            language_id=language_id, kind=kind, ref=ref, achieved_on=today_local(), seen=False
        )
    )
    return True


def check_milestones(language: Language) -> list[NewMilestone]:
    """Call right after committing a new/edited session. Returns milestones
    that were just newly reached (and records them so they won't fire again).
    Caller is responsible for committing the session afterward.
    """
    new: list[NewMilestone] = []
    progress = compute_overall_progress(language)

    for lp in progress.levels:
        if lp.status in ("done", "current") and lp.filled_minutes >= lp.level.target_minutes > 0:
            if _record_if_new(language.id, "level_hours_reached", lp.level.code):
                new.append(
                    NewMilestone(
                        kind="level_hours_reached",
                        ref=lp.level.code,
                        label=(
                            f"{lp.level.code} complete! "
                            f"{lp.level.target_hours:g} hours of {language.name}."
                        ),
                    )
                )

    total_hours = progress.total_minutes / 60
    for h in HOURS_MILESTONES:
        if total_hours >= h:
            if _record_if_new(language.id, "hours_total", str(h)):
                new.append(
                    NewMilestone(kind="hours_total", ref=str(h), label=f"{h} total hours logged!")
                )

    streaks = compute_streaks(
        language.user_id, language.id, threshold=language.user.streak_min_minutes
    )
    for s in STREAK_MILESTONES:
        if streaks.current_streak >= s:
            if _record_if_new(language.id, "streak", str(s)):
                new.append(
                    NewMilestone(kind="streak", ref=str(s), label=f"{s}-day streak! Keep it up.")
                )

    if new:
        db.session.commit()
    return new
