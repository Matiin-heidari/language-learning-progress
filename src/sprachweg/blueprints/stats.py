from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from sprachweg.models import MilestoneEvent
from sprachweg.services.context import get_current_language, list_activity_types
from sprachweg.services.heatmap import build_heatmap
from sprachweg.services.progress import compute_overall_progress
from sprachweg.services.stats import activity_split_all_time, weekly_breakdown

bp = Blueprint("stats", __name__)


@bp.before_request
@login_required
def _require_login():
    pass


@bp.before_request
def _require_language():
    if get_current_language() is None:
        return redirect(url_for("dashboard.index"))
    return None


@bp.route("/stats")
def index():
    language = get_current_language()
    weeks = request.args.get("weeks", default=12, type=int)
    weekly = weekly_breakdown(language.id, weeks=weeks)
    split = activity_split_all_time(language.id)
    activities = {a.key: a for a in list_activity_types()}
    progress = compute_overall_progress(language)
    heatmap = build_heatmap(
        current_user.id, language.id, days=365, week_start=current_user.week_start
    )
    milestones = (
        MilestoneEvent.query.filter_by(language_id=language.id)
        .order_by(MilestoneEvent.achieved_on.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "stats.html",
        language=language,
        weekly=weekly,
        weeks=weeks,
        split=split,
        activities=activities,
        progress=progress,
        heatmap=heatmap,
        milestones=milestones,
    )


@bp.route("/api/stats/weekly")
def api_weekly():
    language = get_current_language()
    weeks = request.args.get("weeks", default=26, type=int)
    weekly = weekly_breakdown(language.id, weeks=weeks)
    activities = list_activity_types()

    datasets = []
    for a in activities:
        datasets.append(
            {
                "key": a.key,
                "label": a.name,
                "colorSlot": a.color_slot,
                "data": [round(w.by_activity.get(a.key, 0) / 60, 2) for w in weekly],
            }
        )

    return jsonify(
        {
            "labels": [w.label for w in weekly],
            "datasets": datasets,
        }
    )
