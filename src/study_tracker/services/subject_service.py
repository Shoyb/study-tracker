"""Subject service – all business logic for managing subjects.

Layering rule: this module imports from ``core``, ``domain`` and ``db`` only.
No Qt imports here.
"""

from __future__ import annotations

import logging
import sqlite3

from study_tracker.core.errors import ConflictError, NotFoundError
from study_tracker.db import subject_daily_goals_repo, subjects_repo
from study_tracker.db.subjects_repo import Subject
from study_tracker.domain.validation import validate_subject_colour, validate_subject_name
from study_tracker.services.undo.adapters import snapshot
from study_tracker.services.undo.journal import JournalService

log = logging.getLogger(__name__)

# Names reserved for system-managed categories.
_PROTECTED = frozenset({"no subject"})


def _assert_exists(subject: Subject | None, subject_id: int) -> Subject:
    if subject is None:
        raise NotFoundError(f"Subject {subject_id} not found.")
    return subject


def _check_unique(conn: sqlite3.Connection, name: str, exclude_id: int | None = None) -> None:
    existing = subjects_repo.get_by_name(conn, name)
    if existing and existing.id != exclude_id:
        raise ConflictError(f"A subject named \"{name}\" already exists.")


def get_all(conn: sqlite3.Connection, *, include_archived: bool = True) -> list[Subject]:
    return subjects_repo.get_all(conn, include_archived=include_archived)


def get_active(conn: sqlite3.Connection) -> list[Subject]:
    """Return non-archived subjects, used to populate pickers."""
    return subjects_repo.get_all(conn, include_archived=False)


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    colour: str = "#1976D2",
    created_at: str,
) -> Subject:
    name = validate_subject_name(name)
    colour = validate_subject_colour(colour)
    _check_unique(conn, name)

    next_order = subjects_repo.max_sort_order(conn) + 1
    with JournalService(conn).action("Create subject", created_at) as record:
        new_id = subjects_repo.insert(
            conn, name=name, colour=colour, sort_order=next_order, created_at=created_at
        )
        record("subject", new_id, "create", None, snapshot(conn, "subject", new_id))
    log.info("Subject created: id=%d name=%r", new_id, name)
    subject = subjects_repo.get_by_id(conn, new_id)
    assert subject is not None
    return subject


def rename(
    conn: sqlite3.Connection,
    subject_id: int,
    *,
    new_name: str,
) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    return update(
        conn,
        subject_id,
        name=new_name,
        colour=subject.colour,
        created_at=subject.created_at,
        summary="Rename subject",
    )


def update(
    conn: sqlite3.Connection,
    subject_id: int,
    *,
    name: str,
    colour: str,
    created_at: str,
    summary: str = "Edit subject",
) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    name = validate_subject_name(name)
    if subject.name.casefold() in _PROTECTED and name.casefold() != subject.name.casefold():
        raise ConflictError(f'The "{subject.name}" category cannot be renamed.')
    colour = validate_subject_colour(colour)
    _check_unique(conn, name, exclude_id=subject_id)
    before = snapshot(conn, "subject", subject_id)
    with JournalService(conn).action(summary, created_at) as record:
        subjects_repo.update(
            conn,
            subject_id,
            name=name,
            colour=colour,
            sort_order=subject.sort_order,
            archived=subject.archived,
        )
        record("subject", subject_id, "update", before, snapshot(conn, "subject", subject_id))
    log.info("Subject %d updated to %r", subject_id, name)
    return subjects_repo.get_by_id(conn, subject_id)  # type: ignore[return-value]


def recolour(
    conn: sqlite3.Connection,
    subject_id: int,
    *,
    colour: str,
) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    return update(
        conn,
        subject_id,
        name=subject.name,
        colour=colour,
        created_at=subject.created_at,
        summary="Recolour subject",
    )


def reorder(conn: sqlite3.Connection, ordered_ids: list[int]) -> None:
    """Set sort_order for each subject according to the given list position."""
    existing = [subjects_repo.get_by_id(conn, subject_id) for subject_id in ordered_ids]
    valid = [subject for subject in existing if subject is not None]
    if not valid:
        return
    now_utc = max(subject.created_at for subject in valid)
    with JournalService(conn).action("Reorder subjects", now_utc) as record:
        for position, subject in enumerate(valid, start=1):
            before = snapshot(conn, "subject", subject.id)
            subjects_repo.update(
                conn,
                subject.id,
                name=subject.name,
                colour=subject.colour,
                sort_order=position,
                archived=subject.archived,
            )
            record("subject", subject.id, "update", before, snapshot(conn, "subject", subject.id))
    log.info("Subjects reordered: %s", ordered_ids)


def archive(conn: sqlite3.Connection, subject_id: int, now_utc: str | None = None) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    if subject.name.casefold() in _PROTECTED:
        raise ConflictError(f'The "{subject.name}" category cannot be archived.')
    before = snapshot(conn, "subject", subject_id)
    with JournalService(conn).action("Archive subject", now_utc or subject.created_at) as record:
        subjects_repo.update(
            conn, subject_id,
            name=subject.name,
            colour=subject.colour,
            sort_order=subject.sort_order,
            archived=True,
        )
        record("subject", subject_id, "update", before, snapshot(conn, "subject", subject_id))
    log.info("Subject %d archived.", subject_id)
    return subjects_repo.get_by_id(conn, subject_id)  # type: ignore[return-value]


def unarchive(conn: sqlite3.Connection, subject_id: int, now_utc: str | None = None) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    before = snapshot(conn, "subject", subject_id)
    with JournalService(conn).action("Unarchive subject", now_utc or subject.created_at) as record:
        subjects_repo.update(
            conn, subject_id,
            name=subject.name,
            colour=subject.colour,
            sort_order=subject.sort_order,
            archived=False,
        )
        record("subject", subject_id, "update", before, snapshot(conn, "subject", subject_id))
    log.info("Subject %d unarchived.", subject_id)
    return subjects_repo.get_by_id(conn, subject_id)  # type: ignore[return-value]


def delete(conn: sqlite3.Connection, subject_id: int, now_utc: str | None = None) -> None:
    """Delete a subject.  Raises if tasks or sessions reference it."""
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    if subject.name.casefold() in _PROTECTED:
        raise ConflictError(f'The "{subject.name}" category cannot be deleted.')

    # Check for referencing tasks.
    task_row = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    if task_row[0] > 0:
        raise ConflictError(
            f"Cannot delete: {task_row[0]} task(s) are linked to this subject. "
            "Archive the subject instead, or reassign the tasks first."
        )

    # Check for referencing sessions.
    sess_row = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    if sess_row[0] > 0:
        raise ConflictError(
            f"Cannot delete: {sess_row[0]} session(s) are linked to this subject. "
            "Archive the subject instead."
        )

    before = snapshot(conn, "subject", subject_id)
    with JournalService(conn).action("Delete subject", now_utc or subject.created_at) as record:
        subject_daily_goals_repo.remove_subject(conn, subject_id)
        subjects_repo.delete(conn, subject_id)
        record("subject", subject_id, "delete", before, None)
    log.info("Subject %d deleted.", subject_id)
