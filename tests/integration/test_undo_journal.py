"""Persistent journal behavior for grouped undo and redo."""

from __future__ import annotations

from pathlib import Path

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.core.errors import ConflictError
from study_tracker.db import journal_repo, sessions_repo, subjects_repo, tasks_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services import session_service, subject_service, task_service
from study_tracker.services.timer_service import TimerService
from study_tracker.services.undo.adapters import snapshot
from study_tracker.services.undo.journal import JournalService


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "undo.db"
    connection = get_connection(db_path)
    run_migrations(connection, db_path)
    yield connection
    connection.close()


def test_undo_redo_create_keeps_original_id(conn):
    journal = JournalService(conn)
    with journal.action("Create subject", "2026-10-13T12:00:00Z") as record:
        subject_id = subjects_repo.insert(
            conn,
            name="Astronomy",
            colour="#123456",
            sort_order=6,
            created_at="2026-10-13T12:00:00Z",
        )
        record("subject", subject_id, "create", None, snapshot(conn, "subject", subject_id))

    assert journal.undo("2026-10-13T12:01:00Z") == "Create subject"
    assert subjects_repo.get_by_id(conn, subject_id) is None
    assert journal.redo("2026-10-13T12:02:00Z") == "Create subject"
    restored = subjects_repo.get_by_id(conn, subject_id)
    assert restored is not None
    assert restored.name == "Astronomy"
    assert journal_repo.latest_group(conn, undone=False) is not None


def test_new_action_clears_redo_stack(conn):
    journal = JournalService(conn)
    with journal.action("Create subject", "2026-10-13T12:00:00Z") as record:
        subject_id = subjects_repo.insert(
            conn,
            name="Astronomy",
            colour="#123456",
            sort_order=6,
            created_at="2026-10-13T12:00:00Z",
        )
        record("subject", subject_id, "create", None, snapshot(conn, "subject", subject_id))
    journal.undo("2026-10-13T12:01:00Z")

    with journal.action("Create another subject", "2026-10-13T12:02:00Z") as record:
        other_id = subjects_repo.insert(
            conn,
            name="Geology",
            colour="#654321",
            sort_order=6,
            created_at="2026-10-13T12:02:00Z",
        )
        record("subject", other_id, "create", None, snapshot(conn, "subject", other_id))

    assert journal.redo("2026-10-13T12:03:00Z") is None


def test_failed_change_rolls_back_entity_and_journal(conn):
    journal = JournalService(conn)
    with pytest.raises(RuntimeError):
        with journal.action("Create subject", "2026-10-13T12:00:00Z") as record:
            subject_id = subjects_repo.insert(
                conn,
                name="Astronomy",
                colour="#123456",
                sort_order=6,
                created_at="2026-10-13T12:00:00Z",
            )
            record("subject", subject_id, "create", None, snapshot(conn, "subject", subject_id))
            raise RuntimeError("simulated failure")

    assert subjects_repo.get_by_name(conn, "Astronomy") is None
    assert journal_repo.list_recent(conn) == []


def test_undo_timer_like_session_restores_task_status_and_redo_keeps_ids(conn):
    task = task_service.create(
        conn,
        subject_id=1,
        title="Chapter review",
        created_at="2026-10-13T10:00:00Z",
    )
    created_session = session_service.add_manual_duration(
        conn,
        subject_id=1,
        task_id=task.id,
        local_date="2026-10-13",
        duration_secs=1800,
        created_at="2026-10-13T11:00:00Z",
    )
    assert tasks_repo.get_by_id(conn, task.id).status == "in_progress"

    journal = JournalService(conn)
    assert journal.undo("2026-10-13T12:00:00Z") == "Add duration session"
    assert sessions_repo.get_by_id(conn, created_session.id) is None
    assert tasks_repo.get_by_id(conn, task.id).status == "todo"

    assert journal.redo("2026-10-13T12:01:00Z") == "Add duration session"
    restored_session = sessions_repo.get_by_id(conn, created_session.id)
    assert restored_session is not None
    assert restored_session.uuid == created_session.uuid
    assert tasks_repo.get_by_id(conn, task.id).status == "in_progress"


def test_task_service_create_and_edit_are_undoable(conn):
    task = task_service.create(
        conn,
        subject_id=1,
        title="Original title",
        created_at="2026-10-13T10:00:00Z",
    )
    journal = JournalService(conn)
    assert journal.undo("2026-10-13T10:01:00Z") == "Create task"
    assert tasks_repo.get_by_id(conn, task.id) is None
    journal.redo("2026-10-13T10:02:00Z")
    assert tasks_repo.get_by_id(conn, task.id).uuid == task.uuid

    task = tasks_repo.get_by_id(conn, task.id)
    task_service.update(
        conn,
        task.id,
        subject_id=task.subject_id,
        title="Updated title",
        status=task.status,
        priority=task.priority,
        archived=task.archived,
        due_date=task.due_date,
        estimate_secs=task.estimate_secs,
        notes=task.notes,
        completed_at=task.completed_at,
        now_utc="2026-10-13T10:03:00Z",
    )
    assert journal.undo("2026-10-13T10:04:00Z") == "Edit task"
    assert tasks_repo.get_by_id(conn, task.id).title == "Original title"


def test_subject_create_edit_and_delete_are_undoable(conn):
    subject = subject_service.create(
        conn,
        name="Astronomy",
        colour="#123456",
        created_at="2026-10-13T10:00:00Z",
    )
    journal = JournalService(conn)
    subject_service.update(
        conn,
        subject.id,
        name="Astrophysics",
        colour="#654321",
        created_at="2026-10-13T10:01:00Z",
    )
    assert journal.undo("2026-10-13T10:02:00Z") == "Edit subject"
    assert subjects_repo.get_by_id(conn, subject.id).name == "Astronomy"

    subject_service.delete(conn, subject.id, "2026-10-13T10:03:00Z")
    assert journal.undo("2026-10-13T10:04:00Z") == "Delete subject"
    assert subjects_repo.get_by_id(conn, subject.id).name == "Astronomy"


def test_undo_through_selected_action_reverses_newer_groups(conn):
    first = subject_service.create(
        conn, name="Astronomy", colour="#123456", created_at="2026-10-13T10:00:00Z"
    )
    second = subject_service.create(
        conn, name="Geology", colour="#654321", created_at="2026-10-13T10:01:00Z"
    )
    first_entry = next(
        entry for entry in journal_repo.list_recent(conn) if entry.entity_id == first.id
    )

    assert JournalService(conn).undo_through(first_entry.id, "2026-10-13T10:02:00Z")
    assert subjects_repo.get_by_id(conn, first.id) is None
    assert subjects_repo.get_by_id(conn, second.id) is None


def test_bulk_session_delete_is_one_undo_action(conn):
    first = session_service.add_manual_duration(
        conn,
        subject_id=1,
        local_date="2026-10-13",
        duration_secs=600,
        created_at="2026-10-13T10:00:00Z",
    )
    second = session_service.add_manual_duration(
        conn,
        subject_id=1,
        local_date="2026-10-13",
        duration_secs=900,
        created_at="2026-10-13T10:01:00Z",
    )
    session_service.delete_many(
        conn, [first.id, second.id], now_utc="2026-10-13T10:02:00Z"
    )
    assert sessions_repo.get_by_id(conn, first.id) is None
    assert sessions_repo.get_by_id(conn, second.id) is None

    assert JournalService(conn).undo("2026-10-13T10:03:00Z") == "Delete 2 sessions"
    assert sessions_repo.get_by_id(conn, first.id).uuid == first.uuid
    assert sessions_repo.get_by_id(conn, second.id).uuid == second.uuid


def test_timer_saved_session_can_be_undone_without_restarting_timer(conn):
    clock = FakeClock("2026-10-13T10:00:00Z")
    timer = TimerService(conn, clock)
    timer.start(subject_id=1)
    clock.advance(minutes=2)
    session = timer.stop()

    assert JournalService(conn).undo(clock.now_utc()) == "Save timer session"
    assert sessions_repo.get_by_id(conn, session.id) is None
    assert timer.is_active is False


def test_undo_refuses_to_overwrite_a_row_changed_outside_journal(conn):
    subject = subject_service.create(
        conn, name="Astronomy", colour="#123456", created_at="2026-10-13T10:00:00Z"
    )
    conn.execute("UPDATE subjects SET name = 'External edit' WHERE id = ?", (subject.id,))

    with pytest.raises(RuntimeError, match="changed outside the journal"):
        JournalService(conn).undo("2026-10-13T10:01:00Z")
    assert subjects_repo.get_by_id(conn, subject.id).name == "External edit"


def test_undo_refuses_session_restore_when_it_would_overlap(conn):
    session = session_service.add_manual_timed(
        conn,
        subject_id=1,
        start_utc="2026-10-13T10:00:00Z",
        end_utc="2026-10-13T11:00:00Z",
        utc_offset_mins=0,
        created_at="2026-10-13T12:00:00Z",
    )
    session_service.delete(conn, session.id, now_utc="2026-10-13T12:01:00Z")
    sessions_repo.insert(
        conn,
        uuid="external-session",
        subject_id=1,
        task_id=None,
        local_date="2026-10-13",
        start_utc="2026-10-13T10:30:00Z",
        end_utc="2026-10-13T10:45:00Z",
        duration_secs=900,
        session_type="manual_timed",
        notes="",
        utc_offset_mins=0,
        created_at="2026-10-13T12:02:00Z",
    )

    with pytest.raises(ConflictError, match="overlaps"):
        JournalService(conn).undo("2026-10-13T12:03:00Z")
    assert sessions_repo.get_by_id(conn, session.id) is None


def test_retention_keeps_latest_groups_and_removes_old_groups(conn):
    subject_service.create(
        conn, name="Astronomy", colour="#123456", created_at="2026-09-01T10:00:00Z"
    )
    subject_service.create(
        conn, name="Geology", colour="#654321", created_at="2026-10-13T10:00:00Z"
    )
    journal = JournalService(conn)

    journal.purge("2026-10-13T12:00:00Z", keep_entries=10, keep_days=30)
    assert conn.execute("SELECT COUNT(*) FROM change_journal").fetchone()[0] == 1

    subject_service.create(
        conn, name="Physics II", colour="#123456", created_at="2026-10-13T11:00:00Z"
    )
    subject_service.create(
        conn, name="Biology II", colour="#654321", created_at="2026-10-13T11:01:00Z"
    )
    journal.purge("2026-10-13T12:00:00Z", keep_entries=1, keep_days=365)
    assert conn.execute(
        "SELECT COUNT(DISTINCT group_id) FROM change_journal"
    ).fetchone()[0] == 1
