"""Validated, idempotent imports of this app's task and session CSV files."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from study_tracker.core.errors import ValidationError
from study_tracker.db import imports_repo, sessions_repo, subjects_repo, tasks_repo
from study_tracker.services.backup_service import file_hash

_TASK_FIELDS = {
    "task_uuid",
    "title",
    "description",
    "subject",
    "status",
    "priority",
    "created_at_utc",
}
_SESSION_FIELDS = {
    "session_uuid",
    "local_date",
    "start_utc",
    "end_utc",
    "duration_seconds",
    "entry_type",
    "subject",
    "task_uuid",
    "notes",
    "created_at_utc",
}
_TYPES = {"timer", "manual_timed", "manual_duration", "device"}


def _overlaps(start: str, end: str, other_start: str, other_end: str) -> bool:
    return start < other_end and end > other_start


@dataclass
class ImportPreview:
    filename: str
    total: int = 0
    new: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    exact_file_seen: bool = False


def _read(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValidationError("CSV header is missing required Study Tracker columns.")
        return list(reader)


def _valid_iso(value: str, *, timestamp: bool = False) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ" if timestamp else "%Y-%m-%d")
    except ValueError:
        return False
    return True


def preview_tasks(conn: sqlite3.Connection, path: Path) -> ImportPreview:
    preview = ImportPreview(path.name, exact_file_seen=imports_repo.has_hash(conn, file_hash(path)))
    for line, row in enumerate(_read(path, _TASK_FIELDS), start=2):
        preview.total += 1
        if not row["task_uuid"] or tasks_repo.get_by_uuid(conn, row["task_uuid"]):
            preview.duplicates += 1
        elif not row["title"].strip() or row["status"] not in {"todo", "in_progress", "done"}:
            preview.errors.append(f"Line {line}: title or status is invalid.")
        elif row["priority"] not in {"low", "medium", "high"}:
            preview.errors.append(f"Line {line}: priority is invalid.")
        elif not _valid_iso(row["created_at_utc"], timestamp=True):
            preview.errors.append(f"Line {line}: created timestamp is invalid.")
        elif row.get("due_date") and not _valid_iso(row["due_date"]):
            preview.errors.append(f"Line {line}: due date is invalid.")
        elif row.get("estimate_seconds") and not row["estimate_seconds"].isdigit():
            preview.errors.append(f"Line {line}: estimate must be a non-negative integer.")
        elif subjects_repo.get_by_name(conn, row["subject"]) is None:
            preview.errors.append(f"Line {line}: subject {row['subject']!r} does not exist.")
        else:
            preview.new += 1
            preview.rows.append(row)
    return preview


def preview_sessions(conn: sqlite3.Connection, path: Path) -> ImportPreview:
    preview = ImportPreview(path.name, exact_file_seen=imports_repo.has_hash(conn, file_hash(path)))
    accepted_timed: list[tuple[str, str]] = []
    for line, row in enumerate(_read(path, _SESSION_FIELDS), start=2):
        preview.total += 1
        source, source_id = row.get("source", ""), row.get("source_id", "")
        if not row["session_uuid"] or sessions_repo.get_by_uuid(conn, row["session_uuid"]):
            preview.duplicates += 1
            continue
        if source and source_id and sessions_repo.get_by_source_id(conn, source, source_id):
            preview.duplicates += 1
            continue
        try:
            duration = int(row["duration_seconds"])
        except ValueError:
            duration = 0
        timed = bool(row["start_utc"] or row["end_utc"])
        if duration <= 0 or row["entry_type"] not in _TYPES or not _valid_iso(row["local_date"]):
            preview.errors.append(f"Line {line}: date, duration, or entry type is invalid.")
        elif timed and (
            not _valid_iso(row["start_utc"], timestamp=True)
            or not _valid_iso(row["end_utc"], timestamp=True)
            or row["end_utc"] <= row["start_utc"]
        ):
            preview.errors.append(f"Line {line}: start and end timestamps are invalid.")
        elif not timed and (row["start_utc"] or row["end_utc"]):
            preview.errors.append(f"Line {line}: timestamps must be both present or both empty.")
        elif subjects_repo.get_by_name(conn, row["subject"]) is None:
            preview.errors.append(f"Line {line}: subject {row['subject']!r} does not exist.")
        elif row.get("task_uuid") and tasks_repo.get_by_uuid(conn, row["task_uuid"]) is None:
            preview.errors.append(f"Line {line}: linked task does not exist; import tasks first.")
        elif timed and sessions_repo.find_overlapping(
            conn, start_utc=row["start_utc"], end_utc=row["end_utc"]
        ):
            preview.errors.append(f"Line {line}: session overlaps an existing session.")
        elif timed and any(
            _overlaps(row["start_utc"], row["end_utc"], prior_start, prior_end)
            for prior_start, prior_end in accepted_timed
        ):
            preview.errors.append(f"Line {line}: session overlaps another imported row.")
        else:
            preview.new += 1
            preview.rows.append(row)
            if timed:
                accepted_timed.append((row["start_utc"], row["end_utc"]))
    return preview


def commit_tasks(
    conn: sqlite3.Connection, path: Path, preview: ImportPreview, imported_at: str
) -> int:
    if preview.exact_file_seen:
        return 0
    with conn:
        for row in preview.rows:
            subject = subjects_repo.get_by_name(conn, row["subject"])
            assert subject is not None
            completed = row.get("completed_at_utc") or None
            status = row["status"]
            if status == "done" and not completed:
                completed = row["created_at_utc"]
            task_id = tasks_repo.insert(
                conn,
                uuid=row["task_uuid"],
                subject_id=subject.id,
                title=row["title"],
                status=status,
                priority=row["priority"],
                due_date=row.get("due_date") or None,
                estimate_secs=int(row["estimate_seconds"]) if row.get("estimate_seconds") else None,
                notes=row.get("description", ""),
                completed_at=completed,
                created_at=row["created_at_utc"],
            )
            if row.get("archived_at_utc"):
                task = tasks_repo.get_by_id(conn, task_id)
                assert task is not None
                tasks_repo.update(
                    conn,
                    task_id,
                    subject_id=task.subject_id,
                    title=task.title,
                    status=task.status,
                    priority=task.priority,
                    archived=True,
                    due_date=task.due_date,
                    estimate_secs=task.estimate_secs,
                    notes=task.notes,
                    completed_at=task.completed_at,
                )
        imports_repo.add(
            conn,
            filename=path.name,
            file_hash=file_hash(path),
            imported_at=imported_at,
            row_count=preview.new,
        )
    return preview.new


def commit_sessions(
    conn: sqlite3.Connection, path: Path, preview: ImportPreview, imported_at: str
) -> int:
    if preview.exact_file_seen:
        return 0
    with conn:
        for row in preview.rows:
            subject = subjects_repo.get_by_name(conn, row["subject"])
            assert subject is not None
            task = (
                tasks_repo.get_by_uuid(conn, row.get("task_uuid", ""))
                if row.get("task_uuid")
                else None
            )
            start, end = row["start_utc"] or None, row["end_utc"] or None
            if start and sessions_repo.find_overlapping(conn, start_utc=start, end_utc=end):
                raise ValidationError(
                    f"Imported session {row['session_uuid']} overlaps an existing session."
                )
            sessions_repo.insert(
                conn,
                uuid=row["session_uuid"],
                subject_id=subject.id,
                task_id=task.id if task else None,
                local_date=row["local_date"],
                start_utc=start,
                end_utc=end,
                duration_secs=int(row["duration_seconds"]),
                session_type=row["entry_type"],
                notes=row.get("notes", ""),
                utc_offset_mins=int(row.get("utc_offset_minutes") or 0),
                source=row.get("source") or "csv_import",
                source_id=row.get("source_id") or row["session_uuid"],
                created_at=row["created_at_utc"],
            )
        imports_repo.add(
            conn,
            filename=path.name,
            file_hash=file_hash(path),
            imported_at=imported_at,
            row_count=preview.new,
        )
    return preview.new
