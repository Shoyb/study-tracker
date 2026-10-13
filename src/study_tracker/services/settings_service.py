"""Business operations for settings that require coordinated data changes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from study_tracker.core.errors import ValidationError
from study_tracker.db import sessions_repo, settings_repo
from study_tracker.domain.day import study_date_for_utc
from study_tracker.services.backup_service import create_backup


def change_study_day_cutoff(
    conn: sqlite3.Connection, cutoff_minutes: int, backup_dir: Path
) -> tuple[int, Path | None]:
    """Back up and atomically recompute timed sessions for a new cutoff."""
    if not 0 <= cutoff_minutes < 1440:
        raise ValidationError("Study-day cutoff must be between 00:00 and 23:59.")

    current = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
    if cutoff_minutes == current:
        return 0, None

    sessions = [session for session in sessions_repo.get_all(conn) if session.start_utc]
    backup_path = create_backup(conn, backup_dir)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for session in sessions:
            local_date = study_date_for_utc(
                session.start_utc or "",
                session.utc_offset_mins,
                cutoff_minutes=cutoff_minutes,
            )
            sessions_repo.update_local_date(conn, session.id, local_date)
        settings_repo.set_value(conn, "day_cutoff_minutes", str(cutoff_minutes))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return len(sessions), backup_path
