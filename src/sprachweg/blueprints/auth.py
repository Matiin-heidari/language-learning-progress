"""Account creation and sign-in. Replaces the old single-password gate now
that there are real per-user accounts (see PLAN.md's multi-user extension).
"""

from __future__ import annotations

import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from sprachweg.extensions import db
from sprachweg.models import User
from sprachweg.seed import seed_user_language

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    error = None
    username = ""
    display_name = ""
    email = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip() or username
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not USERNAME_RE.match(username):
            error = "Username must be 3-20 characters: lowercase letters, numbers, underscore."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."
        elif email and User.query.filter_by(email=email).first():
            error = "That email is already registered."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords don't match."

        if error is None:
            user = User(username=username, display_name=display_name, email=email or None)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            seed_user_language(user)
            login_user(user)
            flash(f"Welcome, {user.display_name}! Your German tracker is ready.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template(
        "signup.html", error=error, username=username, display_name=display_name, email=email
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        identifier = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
        if user is not None and user.check_password(password):
            login_user(user, remember=True)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("dashboard.index"))
        error = "Wrong username or password."

    return render_template("login.html", error=error)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("main.landing"))
