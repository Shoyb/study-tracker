"""Subject service – all business logic for managing subjects.

Layering rule: this module imports from ``core``, ``domain`` and ``db`` only.
No Qt imports here.
"""

from __future__ import annotations

import logging
import sqlite3

from study_tracker.core.errors import ConflictError, NotFoundError
from study_tracker.db import subjects_repo
from study_tracker.db.subjects_repo import Subject
from study_tracker.domain.validation import validate_subject_colour, validate_subject_name

log = logging.getLogger(__name__)

# Names that may never be renamed, archived or deleted.
_PROTECTED = frozenset()  # No hard-coded protected names per plan; Uncategorized removed


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
    new_id = subjects_repo.insert(
        conn, name=name, colour=colour, sort_order=next_order, created_at=created_at
    )
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
    new_name = validate_subject_name(new_name)
    _check_unique(conn, new_name, exclude_id=subject_id)

    subjects_repo.update(
        conn, subject_id,
        name=new_name,
        colour=subject.colour,
        sort_order=subject.sort_order,
        archived=subject.archived,
    )
    log.info("Subject %d renamed to %r", subject_id, new_name)
    return subjects_repo.get_by_id(conn, subject_id)  # type: ignore[return-value]


def recolour(
    conn: sqlite3.Connection,
    subject_id: int,
    *,
    colour: str,
) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    colour = validate_subject_colour(colour)

    subjects_repo.update(
        conn, subject_id,
        name=subject.name,
        colour=colour,
        sort_order=subject.sort_order,
        archived=subject.archived,
    )
    log.info("Subject %d recoloured to %s", subject_id, colour)
    return subjects_repo.get_by_id(conn, subject_id)  # type: ignore[return-value]


def reorder(conn: sqlite3.Connection, ordered_ids: list[int]) -> None:
    """Set sort_order for each subject according to the given list position."""
    for position, subject_id in enumerate(ordered_ids, start=1):
        subject = subjects_repo.get_by_id(conn, subject_id)
        if subject is None:
            continue
        subjects_repo.update(
            conn, subject_id,
            name=subject.name,
            colour=subject.colour,
            sort_order=position,
            archived=subject.archived,
        )
    log.info("Subjects reordered: %s", ordered_ids)


def archive(conn: sqlite3.Connection, subject_id: int) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    subjects_repo.update(
        conn, subject_id,
        name=subject.name,
        colour=subject.colour,
        sort_order=subject.sort_order,
        archived=True,
    )
    log.info("Subject %d archived.", subject_id)
    return subjects_repo.get_by_id(conn, subject_id)  # type: ignore[return-value]


def unarchive(conn: sqlite3.Connection, subject_id: int) -> Subject:
    subject = _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)
    subjects_repo.update(
        conn, subject_id,
        name=subject.name,
        colour=subject.colour,
        sort_order=subject.sort_order,
        archived=False,
    )
    log.info("Subject %d unarchived.", subject_id)
    return subjects_repo.get_by_id(conn, subject_id)  # type: ignore[return-value]


def delete(conn: sqlite3.Connection, subject_id: int) -> None:
    """Delete a subject.  Raises if tasks or sessions reference it."""
    _assert_exists(subjects_repo.get_by_id(conn, subject_id), subject_id)

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

    subjects_repo.delete(conn, subject_id)
    log.info("Subject %d deleted.", subject_id)
