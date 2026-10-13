"""Atomic UTF-8-BOM CSV exports for user-owned study data."""

from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

from study_tracker.db import sessions_repo, settings_repo, subjects_repo, tasks_repo
from study_tracker.services.stats_service import totals_for_range


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> Path:
    """Write a CSV atomically and refuse to overwrite an existing file."""
    if path.exists():
        raise FileExistsError(f"Export already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def export_sessions(
    conn: sqlite3.Connection,
    path: Path,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Path:
    subjects = {item.id: item.name for item in subjects_repo.get_all(conn)}
    tasks = {item.id: item for item in tasks_repo.get_all(conn, include_archived=True)}
    fields = [
        "session_uuid",
        "local_date",
        "start_utc",
        "end_utc",
        "utc_offset_minutes",
        "duration_seconds",
        "entry_type",
        "subject",
        "task_uuid",
        "task_title",
        "notes",
        "source",
        "source_id",
        "created_at_utc",
        "updated_at_utc",
    ]
    rows = []
    for session in sessions_repo.get_all(conn, date_from=date_from, date_to=date_to):
        task = tasks.get(session.task_id)
        rows.append(
            {
                "session_uuid": session.uuid,
                "local_date": session.local_date,
                "start_utc": session.start_utc or "",
                "end_utc": session.end_utc or "",
                "utc_offset_minutes": session.utc_offset_mins if session.start_utc else "",
                "duration_seconds": session.duration_secs,
                "entry_type": session.session_type,
                "subject": subjects.get(session.subject_id, ""),
                "task_uuid": task.uuid if task else "",
                "task_title": task.title if task else "",
                "notes": session.notes,
                "source": session.source or "",
                "source_id": session.source_id or "",
                "created_at_utc": session.created_at,
                "updated_at_utc": session.updated_at or "",
            }
        )
    return _write_rows(path, fields, rows)


def export_tasks(conn: sqlite3.Connection, path: Path) -> Path:
    subjects = {item.id: item.name for item in subjects_repo.get_all(conn)}
    fields = [
        "task_uuid",
        "title",
        "description",
        "subject",
        "status",
        "priority",
        "due_date",
        "estimate_seconds",
        "created_at_utc",
        "completed_at_utc",
        "archived_at_utc",
        "time_spent_seconds",
        "session_count",
    ]
    rows = []
    for task in tasks_repo.get_all(conn, include_archived=True):
        row = conn.execute("SELECT COUNT(*) FROM sessions WHERE task_id = ?", (task.id,)).fetchone()
        rows.append(
            {
                "task_uuid": task.uuid or "",
                "title": task.title,
                "description": task.notes,
                "subject": subjects.get(task.subject_id, ""),
                "status": task.status,
                "priority": task.priority,
                "due_date": task.due_date or "",
                "estimate_seconds": task.estimate_secs or "",
                "created_at_utc": task.created_at,
                "completed_at_utc": task.completed_at or "",
                "archived_at_utc": "" if not task.archived else task.created_at,
                "time_spent_seconds": task.time_spent_secs,
                "session_count": row[0],
            }
        )
    return _write_rows(path, fields, rows)


def export_daily_totals(
    conn: sqlite3.Connection, path: Path, *, date_from: str, date_to: str
) -> Path:
    totals = totals_for_range(conn, start=date_from, end=date_to)
    sessions = sessions_repo.get_all(
        conn,
        date_from=(date.fromisoformat(date_from) - timedelta(days=1)).isoformat(),
        date_to=date_to,
    )
    rows = []
    for day, seconds in totals.items():
        count = sum(1 for session in sessions if session.local_date == day)
        rows.append({"date": day, "total_seconds": seconds, "session_count": count})
    return _write_rows(path, ["date", "total_seconds", "session_count"], rows)


def export_subject_summary(
    conn: sqlite3.Connection, path: Path, *, date_from: str, date_to: str
) -> Path:
    from study_tracker.domain.stats import subject_totals

    sessions = sessions_repo.get_all(
        conn,
        date_from=(date.fromisoformat(date_from) - timedelta(days=1)).isoformat(),
        date_to=date_to,
    )
    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
    totals = subject_totals(sessions, date_from, date_to, cutoff_minutes)
    names = {item.id: item.name for item in subjects_repo.get_all(conn)}
    grand_total = sum(totals.values())
    rows = [
        {
            "subject": names.get(subject_id, "Unknown"),
            "total_seconds": seconds,
            "session_count": sum(1 for session in sessions if session.subject_id == subject_id),
            "share_of_total": seconds / grand_total if grand_total else 0,
        }
        for subject_id, seconds in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]
    return _write_rows(path, ["subject", "total_seconds", "session_count", "share_of_total"], rows)


def export_daily_by_subject(
    conn: sqlite3.Connection, path: Path, *, date_from: str, date_to: str
) -> Path:
    """Export a long-format daily-by-subject file suitable for a pivot table."""
    from study_tracker.domain.allocation import allocate_by_day

    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
    names = {item.id: item.name for item in subjects_repo.get_all(conn)}
    totals: dict[tuple[str, int], int] = {}
    sessions = sessions_repo.get_all(
        conn,
        date_from=(date.fromisoformat(date_from) - timedelta(days=1)).isoformat(),
        date_to=date_to,
    )
    for session in sessions:
        for day, seconds in allocate_by_day(session, cutoff_minutes).items():
            if date_from <= day <= date_to:
                key = (day, session.subject_id)
                totals[key] = totals.get(key, 0) + seconds
    rows = [
        {"date": day, "subject": names.get(subject_id, "Unknown"), "seconds": seconds}
        for (day, subject_id), seconds in sorted(totals.items())
    ]
    return _write_rows(path, ["date", "subject", "seconds"], rows)
