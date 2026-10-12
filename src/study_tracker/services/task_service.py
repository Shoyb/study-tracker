"""Task service – business rules for tasks."""

from __future__ import annotations

import logging
import sqlite3

from study_tracker.core.errors import ConflictError, NotFoundError
from study_tracker.db import subjects_repo, tasks_repo
from study_tracker.db.tasks_repo import Task
from study_tracker.domain.validation import (
    validate_task_priority,
    validate_task_status,
    validate_task_title,
)

log = logging.getLogger(__name__)


def _assert_subject_exists(conn: sqlite3.Connection, subject_id: int) -> None:
    if subjects_repo.get_by_id(conn, subject_id) is None:
        raise NotFoundError(f"Subject {subject_id} not found.")


def _assert_task_exists(task: Task | None, task_id: int) -> Task:
    if task is None:
        raise NotFoundError(f"Task {task_id} not found.")
    return task


def create(
    conn: sqlite3.Connection,
    *,
    subject_id: int,
    title: str,
    status: str = "todo",
    priority: str = "medium",
    due_date: str | None = None,
    estimate_secs: int | None = None,
    notes: str = "",
    completed_at: str | None = None,
    created_at: str,
) -> Task:
    title = validate_task_title(title)
    status = validate_task_status(status)
    priority = validate_task_priority(priority)
    _assert_subject_exists(conn, subject_id)

    if status == "done" and not completed_at:
        completed_at = created_at

    new_id = tasks_repo.insert(
        conn,
        subject_id=subject_id,
        title=title,
        status=status,
        priority=priority,
        due_date=due_date or None,
        estimate_secs=estimate_secs,
        notes=notes.strip(),
        completed_at=completed_at,
        created_at=created_at,
    )
    log.info("Task created: id=%d title=%r", new_id, title)
    task = tasks_repo.get_by_id(conn, new_id)
    assert task is not None
    return task


def quick_add(
    conn: sqlite3.Connection,
    *,
    subject_id: int,
    title: str,
    created_at: str,
) -> Task:
    """Quick-add a task with status='todo' and priority='medium'."""
    return create(
        conn,
        subject_id=subject_id,
        title=title,
        status="todo",
        priority="medium",
        created_at=created_at,
    )


def update(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    subject_id: int,
    title: str,
    status: str,
    priority: str,
    archived: bool,
    due_date: str | None,
    estimate_secs: int | None,
    notes: str,
    completed_at: str | None,
) -> Task:
    _assert_task_exists(tasks_repo.get_by_id(conn, task_id), task_id)
    _assert_subject_exists(conn, subject_id)
    title = validate_task_title(title)
    status = validate_task_status(status)
    priority = validate_task_priority(priority)

    if status == "done" and not completed_at:
        raise ValueError("Completed task must have completed_at timestamp.")
    if status != "done":
        completed_at = None

    tasks_repo.update(
        conn,
        task_id,
        subject_id=subject_id,
        title=title,
        status=status,
        priority=priority,
        archived=archived,
        due_date=due_date or None,
        estimate_secs=estimate_secs,
        notes=notes.strip(),
        completed_at=completed_at,
    )
    log.info("Task %d updated.", task_id)
    task = tasks_repo.get_by_id(conn, task_id)
    assert task is not None
    return task


def complete(conn: sqlite3.Connection, task_id: int, completed_at: str) -> Task:
    task = _assert_task_exists(tasks_repo.get_by_id(conn, task_id), task_id)
    return update(
        conn,
        task_id,
        subject_id=task.subject_id,
        title=task.title,
        status="done",
        priority=task.priority,
        archived=task.archived,
        due_date=task.due_date,
        estimate_secs=task.estimate_secs,
        notes=task.notes,
        completed_at=completed_at,
    )


def reopen(conn: sqlite3.Connection, task_id: int) -> Task:
    task = _assert_task_exists(tasks_repo.get_by_id(conn, task_id), task_id)
    return update(
        conn,
        task_id,
        subject_id=task.subject_id,
        title=task.title,
        status="todo",
        priority=task.priority,
        archived=task.archived,
        due_date=task.due_date,
        estimate_secs=task.estimate_secs,
        notes=task.notes,
        completed_at=None,
    )


def archive(conn: sqlite3.Connection, task_id: int) -> Task:
    task = _assert_task_exists(tasks_repo.get_by_id(conn, task_id), task_id)
    return update(
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


def unarchive(conn: sqlite3.Connection, task_id: int) -> Task:
    task = _assert_task_exists(tasks_repo.get_by_id(conn, task_id), task_id)
    return update(
        conn,
        task_id,
        subject_id=task.subject_id,
        title=task.title,
        status=task.status,
        priority=task.priority,
        archived=False,
        due_date=task.due_date,
        estimate_secs=task.estimate_secs,
        notes=task.notes,
        completed_at=task.completed_at,
    )


def delete(conn: sqlite3.Connection, task_id: int) -> None:
    _assert_task_exists(tasks_repo.get_by_id(conn, task_id), task_id)
    if tasks_repo.has_sessions(conn, task_id):
        raise ConflictError(
            "Cannot delete task with recorded study sessions. Archive the task instead."
        )
    tasks_repo.delete(conn, task_id)
    log.info("Task %d deleted.", task_id)


def get_by_id(conn: sqlite3.Connection, task_id: int) -> Task | None:
    return tasks_repo.get_by_id(conn, task_id)


def get_all(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
    subject_id: int | None = None,
    status: str | None = None,
) -> list[Task]:
    return tasks_repo.get_all(
        conn,
        include_archived=include_archived,
        subject_id=subject_id,
        status=status,
    )
