"""Full-database backup: a safe, consistent copy of the whole SQLite file
(every user, language, session, plan -- not just one account). Shared by
the `flask backup-db` CLI command and the admin web UI's download button.
"""

from __future__ import annotations

import sqlite3

from flask import current_app

from sprachweg.models import today_local


class NotSqliteError(Exception):
    """Raised when DATABASE_URL isn't a sqlite:/// URI -- this backup
    mechanism is SQLite-specific; another engine needs its own tool."""


def default_backup_path() -> str:
    from sprachweg.config import INSTANCE_DIR

    stamp = today_local().isoformat()
    return str(INSTANCE_DIR / f"sprachweg-backup-{stamp}.sqlite")


def create_db_backup(out_path: str | None = None) -> str:
    """Write a safe copy of the live SQLite database to `out_path` (or a
    timestamped default under instance/) using SQLite's own backup API, so a
    concurrent write from the running app can't corrupt it. Returns the path
    written to. Raises NotSqliteError if DATABASE_URL isn't SQLite.
    """
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    prefix = "sqlite:///"
    if not uri.startswith(prefix):
        raise NotSqliteError(uri)
    source_path = uri[len(prefix) :]

    out_path = out_path or default_backup_path()

    source_conn = sqlite3.connect(source_path)
    dest_conn = sqlite3.connect(out_path)
    try:
        with dest_conn:
            source_conn.backup(dest_conn)
    finally:
        source_conn.close()
        dest_conn.close()
    return out_path
