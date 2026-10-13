"""Schema migration runner.

Uses SQLite's built-in ``user_version`` pragma as a schema-version counter.
Each migration is a numbered ``.sql`` file in the ``migrations/`` subdirectory.

Rules (enforced by the runner):
- Migration files are applied in ascending numeric order.
- A safety copy of the database is made *before* each migration.
- Applied migrations are never re-run (idempotent on subsequent starts).
- If the on-disk ``user_version`` is *higher* than the latest known migration,
  the app refuses to open the database to prevent data corruption.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# Directory that contains the numbered SQL migration files.
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _migration_files() -> list[tuple[int, Path]]:
    """Return migration files supported by the current application release.

    Version 8 activates exam definitions and scoring. Later extension
    migrations remain inactive until their features are integrated.
    """
    result: list[tuple[int, Path]] = []
    for p in _MIGRATIONS_DIR.glob("*.sql"):
        stem = p.stem
        try:
            num = int(stem.split("_")[0])
            if num > 8:
                log.info("Ignoring unsupported future migration file: %s", p.name)
                continue
            result.append((num, p))
        except (ValueError, IndexError):
            log.warning("Skipping unrecognised migration file: %s", p)
    return sorted(result, key=lambda t: t[0])


def _get_user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version;").fetchone()[0]


def _make_safety_copy(conn: sqlite3.Connection, db_path: Path, version: int) -> None:
    """Back up the live database, including WAL contents, before a migration."""
    dest = db_path.parent / f"{db_path.stem}.before_m{version:03d}{db_path.suffix}"
    dest_conn: sqlite3.Connection | None = None
    try:
        dest_conn = sqlite3.connect(str(dest))
        conn.backup(dest_conn)
        log.info("Safety copy created: %s", dest)
    except (OSError, sqlite3.Error) as exc:
        log.warning("Could not create safety copy: %s", exc)
    finally:
        if dest_conn is not None:
            dest_conn.close()


def run_migrations(conn: sqlite3.Connection, db_path: Path) -> None:
    """Apply any pending migrations to ``conn``.

    Must be called *after* the connection is opened and pragmas are set.

    Raises:
        RuntimeError: If the on-disk version is newer than the latest known
                      migration (opened by a newer version of the app).
    """
    migrations = _migration_files()
    if not migrations:
        log.warning("No migration files found in %s.", _MIGRATIONS_DIR)
        return

    latest_known = migrations[-1][0]
    current = _get_user_version(conn)

    if current > latest_known:
        raise RuntimeError(
            f"Database schema version {current} is newer than this app knows "
            f"(latest: {latest_known}). Please upgrade Study Tracker."
        )

    for version, path in migrations:
        if version <= current:
            continue  # Already applied.

        log.info("Applying migration %03d from %s …", version, path.name)
        if db_path.exists() and db_path.stat().st_size > 0:
            _make_safety_copy(conn, db_path, version)

        sql = path.read_text(encoding="utf-8")
        # executescript commits any open transaction and then runs the SQL.
        conn.executescript(sql)
        log.info("Migration %03d applied successfully.", version)

    final = _get_user_version(conn)
    # Migration 002 adds task UUIDs.  Generate them here because SQLite has no
    # portable UUID function and old databases must retain their task links.
    from study_tracker.db.tasks_repo import ensure_uuids

    ensure_uuids(conn)
    log.info("Database schema version: %d", final)


def latest_known_version() -> int:
    """Return the newest schema version this app can safely open."""
    migrations = _migration_files()
    return migrations[-1][0] if migrations else 0


def log_row_counts(conn: sqlite3.Connection) -> None:
    """Log the row count of each main table at startup."""
    tables = ["subjects", "tasks", "sessions", "settings"]
    parts = []
    for table in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]  # noqa: S608
            parts.append(f"{table}={count}")
        except sqlite3.OperationalError:
            parts.append(f"{table}=?")
    log.info("Row counts: %s", ", ".join(parts))
