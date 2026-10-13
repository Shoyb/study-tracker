"""Session service – business rules for recording, validating and updating sessions."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime

from study_tracker.core.errors import ConflictError, NotFoundError, ValidationError
from study_tracker.db import sessions_repo, settings_repo, subjects_repo, tasks_repo
from study_tracker.db.sessions_repo import Session
from study_tracker.domain.day import study_date_for_utc
from study_tracker.domain.validation import (
    validate_duration_secs,
    validate_session_times,
    validate_session_type,
)
from study_tracker.services.undo.adapters import snapshot
from study_tracker.services.undo.journal import JournalService

log = logging.getLogger(__name__)


def _assert_subject_exists(conn: sqlite3.Connection, subject_id: int) -> None:
    if subjects_repo.get_by_id(conn, subject_id) is None:
        raise NotFoundError(f"Subject {subject_id} not found.")


def _assert_task_exists(conn: sqlite3.Connection, task_id: int) -> None:
    if tasks_repo.get_by_id(conn, task_id) is None:
        raise NotFoundError(f"Task {task_id} not found.")


def _derive_local_date(
    utc_iso: str,
    utc_offset_mins: int,
    cutoff_minutes: int = 180,
) -> str:
    return study_date_for_utc(utc_iso, utc_offset_mins, cutoff_minutes=cutoff_minutes)


def _maybe_start_task(conn: sqlite3.Connection, task_id: int | None, record=None) -> None:
    """If the task is in 'todo' status, automatically move it to 'in_progress'."""
    if task_id is None:
        return
    before = snapshot(conn, "task", task_id) if record else None
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
            scheduled_date=task.scheduled_date,
        )
        log.info("Task %d automatically transitioned from todo to in_progress.", task.id)
        if record:
            record("task", task_id, "update", before, snapshot(conn, "task", task_id))


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

    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
    start_dt = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.strptime(end_utc, "%Y-%m-%dT%H:%M:%SZ")
    span_secs = int((end_dt - start_dt).total_seconds())

    if duration_secs is None:
        duration_secs = span_secs

    validate_duration_secs(duration_secs)
    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")
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

    local_date = _derive_local_date(start_utc, utc_offset_mins, cutoff_minutes=cutoff_minutes)
    sess_uuid = str(uuid.uuid4())

    with JournalService(conn).action("Add timed session", created_at) as record:
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
        record("session", new_id, "create", None, snapshot(conn, "session", new_id))
        _maybe_start_task(conn, task_id, record)
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
    with JournalService(conn).action("Add duration session", created_at) as record:
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
        record("session", new_id, "create", None, snapshot(conn, "session", new_id))
        _maybe_start_task(conn, task_id, record)
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
    cutoff_minutes = int(settings_repo.get(conn, "day_cutoff_minutes") or "180")

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
        local_date = _derive_local_date(start_utc, utc_offset_mins, cutoff_minutes=cutoff_minutes)

    journal_at = now_utc or existing.created_at
    before = snapshot(conn, "session", session_id)
    with JournalService(conn).action("Edit session", journal_at) as record:
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
        record("session", session_id, "update", before, snapshot(conn, "session", session_id))
    log.info("Session %d updated.", session_id)
    sess = sessions_repo.get_by_id(conn, session_id)
    assert sess is not None
    return sess


def delete(conn: sqlite3.Connection, session_id: int, now_utc: str | None = None) -> None:
    delete_many(conn, [session_id], now_utc=now_utc)


def delete_many(
    conn: sqlite3.Connection, session_ids: list[int], *, now_utc: str | None = None
) -> int:
    """Delete selected sessions as one undoable action."""
    sessions = [sessions_repo.get_by_id(conn, session_id) for session_id in session_ids]
    if any(session is None for session in sessions):
        missing = next(
            session_id
            for session_id, session in zip(session_ids, sessions, strict=True)
            if session is None
        )
        raise NotFoundError(f"Session {missing} not found.")
    existing = [session for session in sessions if session is not None]
    if not existing:
        return 0
    summary = f"Delete {len(existing)} session{'s' if len(existing) != 1 else ''}"
    timestamp = now_utc or existing[0].created_at
    with JournalService(conn).action(summary, timestamp) as record:
        linked_exams: dict[int, dict] = {}
        for session in existing:
            rows = conn.execute(
                "SELECT id FROM exams WHERE session_id = ?", (session.id,)
            ).fetchall()
            for row in rows:
                linked_exams.setdefault(
                    row["id"], snapshot(conn, "exam", row["id"])
                )
            before = snapshot(conn, "session", session.id)
            sessions_repo.delete(conn, session.id)
            for exam_id, exam_before in linked_exams.items():
                record(
                    "exam",
                    exam_id,
                    "update",
                    exam_before,
                    snapshot(conn, "exam", exam_id),
                )
            record("session", session.id, "delete", before, None)
            linked_exams.clear()
    for session in existing:
        log.info("Session %d deleted.", session.id)
    return len(existing)


def split_unassigned_session(
    conn: sqlite3.Connection,
    session_id: int,
    allocations: dict[int, int],
    *,
    keep_unassigned_seconds: int,
    allow_timed_conversion: bool = False,
    now_utc: str,
) -> list[Session]:
    """Split a No subject session into subject-specific duration records."""
    existing = sessions_repo.get_by_id(conn, session_id)
    if existing is None:
        raise NotFoundError(f"Session {session_id} not found.")
    subject = subjects_repo.get_by_id(conn, existing.subject_id)
    if subject is None or subject.name.casefold() != "no subject":
        raise ValidationError("Only sessions recorded as No subject can be split.")
    if existing.task_id is not None:
        raise ValidationError("A session linked to a task cannot be split.")
    if existing.pomodoro_run_id is not None:
        raise ValidationError("A Pomodoro session cannot be split without changing its count.")
    if not isinstance(keep_unassigned_seconds, int) or keep_unassigned_seconds < 0:
        raise ValidationError("Unassigned time cannot be negative.")
    if not allocations and keep_unassigned_seconds == existing.duration_secs:
        return [existing]
    if existing.start_utc and not allow_timed_conversion:
        raise ValidationError("Confirm converting this timed session to duration-only records.")
    if not allocations:
        raise ValidationError("Choose at least one subject for the split.")

    normalized: dict[int, int] = {}
    for subject_id, seconds in allocations.items():
        if not isinstance(subject_id, int) or isinstance(subject_id, bool):
            raise ValidationError("Each split must select a valid subject.")
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            raise ValidationError("Each subject allocation must be a positive number of seconds.")
        _assert_subject_exists(conn, subject_id)
        target = subjects_repo.get_by_id(conn, subject_id)
        if target is None or target.name.casefold() == "no subject":
            raise ValidationError("Choose named subjects for allocated time.")
        normalized[subject_id] = seconds

    if sum(normalized.values()) + keep_unassigned_seconds != existing.duration_secs:
        raise ValidationError(
            "Subject allocations and unassigned time must equal the session total."
        )

    local_date = existing.local_date
    notes = existing.notes
    offset = existing.utc_offset_mins
    created: list[Session] = []
    with JournalService(conn).action("Split unassigned session", now_utc) as record:
        for subject_id, seconds in normalized.items():
            new_id = sessions_repo.insert(
                conn,
                uuid=str(uuid.uuid4()),
                subject_id=subject_id,
                task_id=None,
                local_date=local_date,
                start_utc=None,
                end_utc=None,
                duration_secs=seconds,
                session_type="manual_duration",
                notes=notes,
                utc_offset_mins=offset,
                created_at=now_utc,
            )
            record("session", new_id, "create", None, snapshot(conn, "session", new_id))
            split_session = sessions_repo.get_by_id(conn, new_id)
            assert split_session is not None
            created.append(split_session)

        if keep_unassigned_seconds:
            before = snapshot(conn, "session", session_id)
            sessions_repo.update(
                conn,
                session_id,
                subject_id=existing.subject_id,
                task_id=None,
                local_date=local_date,
                start_utc=None,
                end_utc=None,
                duration_secs=keep_unassigned_seconds,
                session_type="manual_duration",
                notes=notes,
                utc_offset_mins=offset,
            )
            record(
                "session", session_id, "update", before, snapshot(conn, "session", session_id)
            )
            retained = sessions_repo.get_by_id(conn, session_id)
            assert retained is not None
            created.append(retained)
        else:
            before = snapshot(conn, "session", session_id)
            sessions_repo.delete(conn, session_id)
            record("session", session_id, "delete", before, None)

    return created


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
