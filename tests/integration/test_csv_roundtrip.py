"""CSV export/import integration checks."""

from __future__ import annotations

from pathlib import Path

from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services import session_service, task_service
from study_tracker.services.export_service import export_daily_totals, export_sessions, export_tasks
from study_tracker.services.import_service import (
    commit_sessions,
    commit_tasks,
    preview_sessions,
    preview_tasks,
)


def _database(path: Path):
    conn = get_connection(path)
    run_migrations(conn, path)
    return conn


def test_export_import_round_trip_is_idempotent(tmp_path):
    source = _database(tmp_path / "source.db")
    task = task_service.create(
        source,
        subject_id=1,
        title="Bengali, বাংলা",
        notes="line one\nline two",
        created_at="2026-10-01T00:00:00Z",
    )
    session_service.add_manual_duration(
        source,
        subject_id=1,
        task_id=task.id,
        local_date="2026-10-02",
        duration_secs=1800,
        notes='comma, quote " and বাংলা',
        created_at="2026-10-02T00:00:00Z",
    )
    tasks_csv, sessions_csv = tmp_path / "tasks.csv", tmp_path / "sessions.csv"
    export_tasks(source, tasks_csv)
    export_sessions(source, sessions_csv)
    source.close()

    target = _database(tmp_path / "target.db")
    task_preview = preview_tasks(target, tasks_csv)
    assert task_preview.new == 1
    assert commit_tasks(target, tasks_csv, task_preview, "2026-10-03T00:00:00Z") == 1
    session_preview = preview_sessions(target, sessions_csv)
    assert session_preview.new == 1
    assert commit_sessions(target, sessions_csv, session_preview, "2026-10-03T00:00:00Z") == 1
    assert preview_sessions(target, sessions_csv).exact_file_seen
    assert target.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    target.close()


def test_daily_export_includes_zero_days(tmp_path):
    conn = _database(tmp_path / "data.db")
    output = tmp_path / "daily.csv"
    export_daily_totals(conn, output, date_from="2026-10-01", date_to="2026-10-03")
    lines = output.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 4
    assert lines[2].endswith(",0,0")
    conn.close()
