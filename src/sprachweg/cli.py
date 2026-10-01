"""Custom `flask` CLI commands: seed, seed-demo, claim-data, export, import."""

from __future__ import annotations

import json
import random
from datetime import timedelta

import click
from flask import Flask

from sprachweg.extensions import db
from sprachweg.models import Language, StudySession, User, today_local
from sprachweg.seed import seed_global_activity_types, seed_user_language
from sprachweg.services.context import list_activity_types


def register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    def seed_command() -> None:
        """Create the shared global activity types (vocab, grammar, ...)."""
        activities = seed_global_activity_types()
        db.session.commit()
        click.echo(f"Seeded {len(activities)} global activity types.")

    @app.cli.command("create-user")
    @click.option("--username", required=True)
    @click.option("--password", required=True)
    @click.option("--email", default=None)
    @click.option("--display-name", default=None)
    def create_user_command(
        username: str, password: str, email: str | None, display_name: str | None
    ) -> None:
        """Create a new account (also seeds it a German language)."""
        username = username.strip().lower()
        if User.query.filter_by(username=username).first():
            click.echo(f"Username '{username}' is already taken.")
            return
        user = User(username=username, display_name=display_name or username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        seed_user_language(user)
        db.session.commit()
        click.echo(f"Created user '{username}' (id={user.id}) with a German language seeded.")

    @app.cli.command("seed-demo")
    @click.option("--username", required=True, help="Account to backfill demo data for.")
    @click.option("--days", default=200, help="How many past days to backfill with demo data.")
    def seed_demo_command(username: str, days: int) -> None:
        """Add randomised realistic sessions for local UI development. Dev only."""
        user = User.query.filter_by(username=username.strip().lower()).first()
        if user is None:
            click.echo(f"No user '{username}' -- create one first with `flask create-user`.")
            return
        language = Language.query.filter_by(user_id=user.id, code="de").first()
        if language is None:
            language = seed_user_language(user)
        activities = list_activity_types(user_id=user.id)
        if not activities:
            click.echo("No activity types found — run `flask seed` first.")
            return

        today = today_local()
        created = 0
        for i in range(days):
            day = today - timedelta(days=i)
            # ~75% chance of studying on a given day, weighted toward recent days
            if random.random() > 0.75:
                continue
            num_sessions = random.choice([1, 1, 2])
            for _ in range(num_sessions):
                activity = random.choice(activities)
                minutes = random.choice([15, 20, 30, 30, 45, 60, 90])
                db.session.add(
                    StudySession(
                        user_id=user.id,
                        language_id=language.id,
                        activity_type_id=activity.id,
                        study_date=day,
                        minutes=minutes,
                    )
                )
                created += 1
        db.session.commit()
        click.echo(f"Created {created} demo sessions over the last {days} days for '{username}'.")

    @app.cli.command("claim-data")
    @click.option("--username", required=True, help="New account to create.")
    @click.option("--password", required=True)
    @click.option("--email", default=None)
    @click.option("--display-name", default=None)
    def claim_data_command(
        username: str, password: str, email: str | None, display_name: str | None
    ) -> None:
        """One-time migration helper: create an account and attach any
        pre-existing single-user data (languages/sessions with no owner yet,
        from before multi-user accounts existed) to it.
        """
        username = username.strip().lower()
        if User.query.filter_by(username=username).first():
            click.echo(f"Username '{username}' is already taken.")
            return

        user = User(username=username, display_name=display_name or username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        orphan_languages = Language.query.filter_by(user_id=None).all()
        for lang in orphan_languages:
            lang.user_id = user.id
        orphan_sessions = StudySession.query.filter_by(user_id=None).all()
        for session in orphan_sessions:
            session.user_id = user.id

        if not orphan_languages:
            seed_user_language(user)

        db.session.commit()
        click.echo(
            f"Created '{username}' and claimed {len(orphan_languages)} language(s) and "
            f"{len(orphan_sessions)} session(s)."
        )

    @app.cli.command("export")
    @click.option("--username", required=True)
    @click.option("--out", default="backup.json", help="Output file path.")
    def export_command(username: str, out: str) -> None:
        """Export one account's data as JSON."""
        from sprachweg.blueprints.settings import build_export_payload

        user = User.query.filter_by(username=username.strip().lower()).first()
        if user is None:
            click.echo(f"No user '{username}'.")
            return
        payload = build_export_payload(user)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        click.echo(f"Exported '{username}' to {out}")

    @app.cli.command("import-data")
    @click.option("--username", required=True)
    @click.argument("path")
    def import_command(username: str, path: str) -> None:
        """Import data from a JSON file previously created with `export`."""
        from sprachweg.blueprints.settings import restore_export_payload

        user = User.query.filter_by(username=username.strip().lower()).first()
        if user is None:
            click.echo(f"No user '{username}'.")
            return
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        restore_export_payload(payload, user)
        click.echo(f"Imported into '{username}' from {path}")
