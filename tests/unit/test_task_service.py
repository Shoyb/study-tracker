"""Unit tests for services/task_service.py."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.core.errors import ConflictError, NotFoundError, ValidationError
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services import task_service


@pytest.fixture()
def conn(tmp_path: pathlib.Path):
    db_path = tmp_path / "test.db"
    c = get_connection(db_path)
    run_migrations(c, db_path)
    yield c
    c.close()


CLOCK = FakeClock("2026-10-13T00:00:00Z")


class TestTaskServiceCreate:
    def test_quick_add(self, conn):
        task = task_service.quick_add(
            conn, subject_id=1, title="Read chapter 1", created_at=CLOCK.now_utc()
        )
        assert task.id > 0
        assert task.title == "Read chapter 1"
        assert task.status == "todo"
        assert task.priority == "medium"
        assert task.completed_at is None
        assert not task.archived

    def test_create_full(self, conn):
        task = task_service.create(
            conn,
            subject_id=1,
            title="Complex Task",
            priority="high",
            due_date="2026-10-20",
            estimate_secs=7200,
            notes="Some notes",
            created_at=CLOCK.now_utc(),
        )
        assert task.title == "Complex Task"
        assert task.priority == "high"
        assert task.due_date == "2026-10-20"
        assert task.estimate_secs == 7200
        assert task.notes == "Some notes"

    def test_create_empty_title_raises(self, conn):
        with pytest.raises(ValidationError):
            task_service.create(conn, subject_id=1, title="   ", created_at=CLOCK.now_utc())

    def test_create_bad_subject_raises(self, conn):
        with pytest.raises(NotFoundError):
            task_service.create(conn, subject_id=9999, title="Valid", created_at=CLOCK.now_utc())


class TestTaskTransitions:
    def test_complete_and_reopen(self, conn):
        task = task_service.quick_add(conn, subject_id=1, title="Task", created_at=CLOCK.now_utc())
        completed = task_service.complete(conn, task.id, completed_at="2026-10-13T12:00:00Z")
        assert completed.status == "done"
        assert completed.completed_at == "2026-10-13T12:00:00Z"

        reopened = task_service.reopen(conn, task.id)
        assert reopened.status == "todo"
        assert reopened.completed_at is None

    def test_archive_and_unarchive(self, conn):
        task = task_service.quick_add(conn, subject_id=1, title="Task", created_at=CLOCK.now_utc())
        archived = task_service.archive(conn, task.id)
        assert archived.archived is True

        unarchived = task_service.unarchive(conn, task.id)
        assert unarchived.archived is False


class TestTaskDelete:
    def test_delete_unused(self, conn):
        task = task_service.quick_add(conn, subject_id=1, title="Task", created_at=CLOCK.now_utc())
        task_service.delete(conn, task.id)
        assert task_service.get_by_id(conn, task.id) is None

    def test_delete_with_sessions_raises_conflict(self, conn):
        task = task_service.quick_add(conn, subject_id=1, title="Task", created_at=CLOCK.now_utc())
        # Insert a session linked to this task
        conn.execute(
            """INSERT INTO sessions
               (uuid, subject_id, task_id, local_date, duration_secs,
                session_type, notes, utc_offset_mins, created_at)
               VALUES ('u-task', 1, ?, '2026-10-13', 3600, 'timer', '',
                       0, '2026-10-13T00:00:00Z')""",
            (task.id,),
        )
        with pytest.raises(ConflictError, match="study sessions"):
            task_service.delete(conn, task.id)
