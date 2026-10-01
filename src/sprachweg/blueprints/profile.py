"""Other learners' public profiles and the cross-user leaderboard. Both
require being signed in yourself -- this is a small-group social feature,
not a public internet page.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from sprachweg.models import Language, User
from sprachweg.services.heatmap import build_heatmap
from sprachweg.services.leaderboard import streak_leaderboard, today_leaderboard, week_leaderboard
from sprachweg.services.progress import compute_overall_progress
from sprachweg.services.streaks import compute_streaks

bp = Blueprint("profile", __name__)


@bp.before_request
@login_required
def _require_login():
    pass


@bp.route("/u/<username>")
def view(username: str):
    user = User.query.filter_by(username=username.lower()).first_or_404()
    is_owner = current_user.id == user.id

    if not user.is_public and not is_owner:
        return render_template("profile_private.html", profile_user=user), 403

    languages = (
        Language.query.filter_by(user_id=user.id, is_active=True).order_by(Language.id).all()
    )
    language_progress = [compute_overall_progress(lang) for lang in languages]

    streaks = compute_streaks(user.id, threshold=user.streak_min_minutes)
    heatmap = build_heatmap(user.id, days=365, week_start=user.week_start)

    return render_template(
        "profile.html",
        profile_user=user,
        is_owner=is_owner,
        language_progress=language_progress,
        streaks=streaks,
        heatmap=heatmap,
    )


@bp.route("/leaderboard")
def leaderboard():
    metric = request.args.get("metric", "today")
    if metric == "week":
        rows = week_leaderboard()
    elif metric == "streak":
        rows = streak_leaderboard()
    else:
        metric = "today"
        rows = today_leaderboard()

    return render_template("leaderboard.html", rows=rows, metric=metric)
