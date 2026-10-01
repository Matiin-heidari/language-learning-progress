"""Public landing page. The app's actual "/" for logged-out visitors; signed
in users are sent straight to the dashboard.
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user

bp = Blueprint("main", __name__)


@bp.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("landing.html")
