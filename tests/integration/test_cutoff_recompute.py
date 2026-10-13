"""Integration tests for changing the study-day cutoff."""

from __future__ import annotations

from pathlib import Path

import pytest

from study_tracker.core.errors import ValidationError
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services.backup_service import backup_report
from study_tracker.services.session_service import add_manual_duration, add_manual_timed
from study_tracker.services.settings_service import change_study_day_cutoff
from study_tracker.services.stats_service import totals_for_range


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    run_migrations(connection, db_path)
    yield connection
    connection.close()


def test_cutoff_change_backs_up_and_recomputes_timed_sessions(conn, tmp_path: Path):
    timed = add_manual_timed(
        conn,
        subject_id=1,
        start_utc="2026-10-13T02:00:00Z",
        end_utc="2026-10-13T02:30:00Z",
        utc_offset_mins=0,
        created_at="2026-10-13T12:00:00Z",
    )
    duration_only = add_manual_duration(
        conn,
        subject_id=1,
        local_date="2026-10-12",
        duration_secs=1800,
        created_at="2026-10-13T12:00:00Z",
    )

    changed, backup = change_study_day_cutoff(conn, 0, tmp_path / "backups")

    assert changed == 1
    assert backup is not None and backup_report(backup).ok
    assert conn.execute(
        "SELECT local_date FROM sessions WHERE id = ?", (timed.id,)
    ).fetchone()[0] == "2026-10-13"
    assert conn.execute(
        "SELECT local_date FROM sessions WHERE id = ?", (duration_only.id,)
    ).fetchone()[0] == "2026-10-12"
    assert totals_for_range(conn, start="2026-10-13", end="2026-10-13") == {
        "2026-10-13": 1800
    }
    assert change_study_day_cutoff(conn, 0, tmp_path / "backups") == (0, None)


def test_invalid_cutoff_does_not_change_settings(conn, tmp_path: Path):
    with pytest.raises(ValidationError):
        change_study_day_cutoff(conn, 1440, tmp_path / "backups")
    assert conn.execute(
        "SELECT value FROM settings WHERE key='day_cutoff_minutes'"
    ).fetchone()[0] == "180"
