"""Custom `flask` CLI commands: seed, seed-demo, claim-data, export, import,
backup-db, export-all.
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import timedelta

import click
from flask import Flask, current_app

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

    @app.cli.command("backup-db")
    @click.option("--out", default=None, help="Output path (default: timestamped, in instance/).")
    def backup_db_command(out: str | None) -> None:
        """Full backup of *every* account in one shot: a safe, consistent
        copy of the whole SQLite file (every user, language, session, plan --
        not just one account). Safe to run while the app is live; uses
        SQLite's own backup API rather than a raw file copy, so a
        concurrent write can't corrupt it. Only works when DATABASE_URL is
        a sqlite:/// URI (the default for this app).
        """
        uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        prefix = "sqlite:///"
        if not uri.startswith(prefix):
            click.echo(
                f"DATABASE_URL isn't SQLite ({uri!r}) -- "
                "back this up with your DB's own tool instead."
            )
            return
        source_path = uri[len(prefix) :]

        if out is None:
            from sprachweg.config import INSTANCE_DIR

            stamp = today_local().isoformat()
            out = str(INSTANCE_DIR / f"sprachweg-backup-{stamp}.sqlite")

        source_conn = sqlite3.connect(source_path)
        dest_conn = sqlite3.connect(out)
        with dest_conn:
            source_conn.backup(dest_conn)
        source_conn.close()
        dest_conn.close()
        click.echo(f"Backed up the full database ({User.query.count()} user(s)) to {out}")

    @app.cli.command("export-all")
    @click.option(
        "--out-dir", default="backups", help="Directory to write one JSON file per account into."
    )
    def export_all_command(out_dir: str) -> None:
        """Export every account's data as JSON, one file per user (named
        <username>.json). Complement to `backup-db`: slower and
        schema-shaped rather than a raw file, but human-readable, diffable,
        and restorable per-account with `import-data`.
        """
        import os

        from sprachweg.blueprints.settings import build_export_payload

        os.makedirs(out_dir, exist_ok=True)
        users = User.query.order_by(User.id).all()
        for user in users:
            payload = build_export_payload(user)
            path = os.path.join(out_dir, f"{user.username}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        click.echo(f"Exported {len(users)} account(s) to {out_dir}/")
