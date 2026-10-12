"""Session service – business rules for recording, validating and updating sessions."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from study_tracker.core.errors import ConflictError, NotFoundError, ValidationError
from study_tracker.db import sessions_repo, subjects_repo, tasks_repo
from study_tracker.db.sessions_repo import Session
from study_tracker.domain.validation import (
    validate_duration_secs,
    validate_session_times,
    validate_session_type,
)

log = logging.getLogger(__name__)


def _assert_subject_exists(conn: sqlite3.Connection, subject_id: int) -> None:
    if subjects_repo.get_by_id(conn, subject_id) is None:
        raise NotFoundError(f"Subject {subject_id} not found.")


def _assert_task_exists(conn: sqlite3.Connection, task_id: int) -> None:
    if tasks_repo.get_by_id(conn, task_id) is None:
        raise NotFoundError(f"Task {task_id} not found.")


def _derive_local_date(utc_iso: str, utc_offset_mins: int) -> str:
    dt_utc = datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    local_dt = dt_utc + timedelta(minutes=utc_offset_mins)
    return local_dt.strftime("%Y-%m-%d")


def _maybe_start_task(conn: sqlite3.Connection, task_id: int | None) -> None:
    """If the task is in 'todo' status, automatically move it to 'in_progress'."""
    if task_id is None:
        return
    task = tasks_repo.get_by_id(conn, task_id)
    if task and task.status == "todo":
        tasks_repo.update(
            conn,
            task.id,
            subject_id=task.subject_id,
            title=task.title,
            status="in_progress",
            priority=task.priority,
            archived=task.archived,
            due_date=task.due_date,
            estimate_secs=task.estimate_secs,
            notes=task.notes,
            completed_at=None,
        )
        log.info("Task %d automatically transitioned from todo to in_progress.", task.id)


def add_manual_timed(
    conn: sqlite3.Connection,
    *,
    subject_id: int,
    task_id: int | None = None,
    start_utc: str,
    end_utc: str,
    duration_secs: int | None = None,
    notes: str = "",
    utc_offset_mins: int = 0,
    created_at: str,
) -> Session:
    """Add a manual session with exact start and end timestamps."""
    _assert_subject_exists(conn, subject_id)
    if task_id is not None:
        _assert_task_exists(conn, task_id)

    validate_session_times(start_utc, end_utc, now_utc=created_at)

    start_dt = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.strptime(end_utc, "%Y-%m-%dT%H:%M:%SZ")
    span_secs = int((end_dt - start_dt).total_seconds())

    if duration_secs is None:
        duration_secs = span_secs

    validate_duration_secs(duration_secs)
    if duration_secs > span_secs:
        raise ValidationError(
            f"Duration ({duration_secs}s) cannot exceed time span between start and "
            f"end ({span_secs}s)."
        )

    # Overlap check
    overlapping = sessions_repo.find_overlapping(conn, start_utc=start_utc, end_utc=end_utc)
    if overlapping:
        conflict = overlapping[0]
        raise ConflictError(
            f"Session overlaps with an existing session (ID {conflict.id}: "
            f"{conflict.start_utc} to {conflict.end_utc})."
        )

    local_date = _derive_local_date(start_utc, utc_offset_mins)
    sess_uuid = str(uuid.uuid4())

    new_id = sessions_repo.insert(
        conn,
        uuid=sess_uuid,
        subject_id=subject_id,
        task_id=task_id,
        local_date=local_date,
        start_utc=start_utc,
        end_utc=end_utc,
        duration_secs=duration_secs,
        session_type="manual_timed",
        notes=notes.strip(),
        utc_offset_mins=utc_offset_mins,
        created_at=created_at,
    )

    _maybe_start_task(conn, task_id)
    log.info("Manual timed session created: id=%d", new_id)
    sess = sessions_repo.get_by_id(conn, new_id)
    assert sess is not None
    return sess


def add_manual_duration(
    conn: sqlite3.Connection,
    *,
    subject_id: int,
    task_id: int | None = None,
    local_date: str,
    duration_secs: int,
    notes: str = "",
    utc_offset_mins: int = 0,
    created_at: str,
) -> Session:
    """Add a manual session with only a calendar date and duration."""
    _assert_subject_exists(conn, subject_id)
    if task_id is not None:
        _assert_task_exists(conn, task_id)

    validate_duration_secs(duration_secs)

    # Check 24-hour daily total limit
    curr_total = sessions_repo.total_secs_for_date(conn, local_date)
    if curr_total + duration_secs > 86400:
        raise ValidationError(
            f"Cannot add {duration_secs // 3600}h: daily total for {local_date} would "
            f"exceed 24 hours (already {curr_total // 3600}h recorded)."
        )

    sess_uuid = str(uuid.uuid4())
    new_id = sessions_repo.insert(
        conn,
        uuid=sess_uuid,
        subject_id=subject_id,
        task_id=task_id,
        local_date=local_date,
        start_utc=None,
        end_utc=None,
        duration_secs=duration_secs,
        session_type="manual_duration",
        notes=notes.strip(),
        utc_offset_mins=utc_offset_mins,
        created_at=created_at,
    )

    _maybe_start_task(conn, task_id)
    log.info("Manual duration session created: id=%d", new_id)
    sess = sessions_repo.get_by_id(conn, new_id)
    assert sess is not None
    return sess


def update(
    conn: sqlite3.Connection,
    session_id: int,
    *,
    subject_id: int,
    task_id: int | None,
    local_date: str,
    start_utc: str | None,
    end_utc: str | None,
    duration_secs: int,
    session_type: str,
    notes: str,
    utc_offset_mins: int,
    now_utc: str | None = None,
) -> Session:
    """Update an existing session with overlap and validation checking."""
    existing = sessions_repo.get_by_id(conn, session_id)
    if existing is None:
        raise NotFoundError(f"Session {session_id} not found.")

    _assert_subject_exists(conn, subject_id)
    if task_id is not None:
        _assert_task_exists(conn, task_id)

    validate_duration_secs(duration_secs)
    validate_session_type(session_type)

    if start_utc and end_utc:
        validate_session_times(start_utc, end_utc, now_utc=now_utc)
        start_dt = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
        end_dt = datetime.strptime(end_utc, "%Y-%m-%dT%H:%M:%SZ")
        span_secs = int((end_dt - start_dt).total_seconds())

        if duration_secs > span_secs:
            raise ValidationError(
                f"Duration ({duration_secs}s) cannot exceed span ({span_secs}s)."
            )

        overlapping = sessions_repo.find_overlapping(
            conn, start_utc=start_utc, end_utc=end_utc, exclude_id=session_id
        )
        if overlapping:
            conflict = overlapping[0]
            raise ConflictError(
                f"Session overlaps with session {conflict.id} "
                f"({conflict.start_utc} to {conflict.end_utc})."
            )
        local_date = _derive_local_date(start_utc, utc_offset_mins)

    sessions_repo.update(
        conn,
        session_id,
        subject_id=subject_id,
        task_id=task_id,
        local_date=local_date,
        start_utc=start_utc,
        end_utc=end_utc,
        duration_secs=duration_secs,
        session_type=session_type,
        notes=notes.strip(),
        utc_offset_mins=utc_offset_mins,
    )
    log.info("Session %d updated.", session_id)
    sess = sessions_repo.get_by_id(conn, session_id)
    assert sess is not None
    return sess


def delete(conn: sqlite3.Connection, session_id: int) -> None:
    existing = sessions_repo.get_by_id(conn, session_id)
    if existing is None:
        raise NotFoundError(f"Session {session_id} not found.")
    sessions_repo.delete(conn, session_id)
    log.info("Session %d deleted.", session_id)


def get_all(
    conn: sqlite3.Connection,
    *,
    subject_id: int | None = None,
    task_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session_type: str | None = None,
    notes_query: str | None = None,
) -> list[Session]:
    return sessions_repo.get_all(
        conn,
        subject_id=subject_id,
        task_id=task_id,
        date_from=date_from,
        date_to=date_to,
        session_type=session_type,
        notes_query=notes_query,
    )
