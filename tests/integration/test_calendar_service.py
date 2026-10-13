"""Calendar event and scheduled-task service behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from study_tracker.core.errors import ValidationError
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services import calendar_service, task_service
from study_tracker.services.undo.journal import JournalService


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "calendar.db"
    connection = get_connection(db_path)
    run_migrations(connection, db_path)
    yield connection
    connection.close()


def test_events_sort_by_position_in_study_day_and_are_undoable(conn):
    late = calendar_service.add_event(
        conn,
        title="Evening class",
        notes="",
        local_date="2026-10-13",
        start_time="23:00",
        end_time="23:30",
        created_at="2026-10-13T10:00:00Z",
    )
    early = calendar_service.add_event(
        conn,
        title="Early class",
        notes="",
        local_date="2026-10-13",
        start_time="01:00",
        end_time="02:00",
        created_at="2026-10-13T10:01:00Z",
    )

    items = calendar_service.get_items_for_date(conn, "2026-10-13")
    assert [item.id for item in items] == [late.id, early.id]
    assert JournalService(conn).undo("2026-10-13T10:02:00Z") == "Add calendar event"
    assert [item.id for item in calendar_service.get_items_for_date(conn, "2026-10-13")] == [
        late.id
    ]


def test_calendar_item_delete_and_redo_preserve_uuid(conn):
    item = calendar_service.add_note(
        conn,
        title="Review notes",
        notes="Chapter 2",
        local_date="2026-10-13",
        created_at="2026-10-13T10:00:00Z",
    )
    calendar_service.delete(conn, item.id, "2026-10-13T10:01:00Z")
    journal = JournalService(conn)
    assert journal.undo("2026-10-13T10:02:00Z") == "Delete calendar item"
    restored = calendar_service.get_items_for_date(conn, item.local_date)[0]
    assert restored.uuid == item.uuid
    assert journal.redo("2026-10-13T10:03:00Z") == "Delete calendar item"
    assert calendar_service.get_items_for_date(conn, item.local_date) == []


def test_event_rejects_invalid_time_range(conn):
    with pytest.raises(ValidationError, match="later"):
        calendar_service.add_event(
            conn,
            title="Invalid",
            notes="",
            local_date="2026-10-13",
            start_time="12:00",
            end_time="11:00",
            created_at="2026-10-13T10:00:00Z",
        )


def test_task_schedule_is_undoable_and_can_be_cleared(conn):
    task = task_service.quick_add(
        conn, subject_id=1, title="Read a chapter", created_at="2026-10-13T10:00:00Z"
    )
    journal = JournalService(conn)
    task = task_service.schedule(conn, task.id, "2026-10-14", "2026-10-13T10:01:00Z")
    assert task.scheduled_date == "2026-10-14"
    assert journal.undo("2026-10-13T10:02:00Z") == "Schedule task"
    assert task_service.get_by_id(conn, task.id).scheduled_date is None
    task_service.schedule(conn, task.id, "2026-10-14", "2026-10-13T10:03:00Z")
    task_service.schedule(conn, task.id, None, "2026-10-13T10:04:00Z")
    assert task_service.get_by_id(conn, task.id).scheduled_date is None


def test_moving_multiple_tasks_is_one_undo_action(conn):
    tasks = [
        task_service.quick_add(
            conn,
            subject_id=1,
            title=f"Task {index}",
            created_at=f"2026-10-13T10:0{index}:00Z",
        )
        for index in (1, 2)
    ]
    for task in tasks:
        task_service.schedule(conn, task.id, "2026-10-12", "2026-10-13T10:03:00Z")
    task_service.schedule_many(
        conn, [task.id for task in tasks], "2026-10-13", "2026-10-13T10:04:00Z"
    )

    journal = JournalService(conn)
    assert journal.undo("2026-10-13T10:05:00Z") == "Move scheduled tasks"
    assert [task_service.get_by_id(conn, task.id).scheduled_date for task in tasks] == [
        "2026-10-12",
        "2026-10-12",
    ]


def test_deleting_task_keeps_calendar_item_text_and_undo_restores_link(conn):
    task = task_service.quick_add(
        conn, subject_id=1, title="Coaching preparation", created_at="2026-10-13T10:00:00Z"
    )
    item = calendar_service.add_event(
        conn,
        title="Coaching",
        notes="Review mechanics",
        local_date="2026-10-14",
        start_time="14:00",
        end_time="15:00",
        task_id=task.id,
        created_at="2026-10-13T10:01:00Z",
    )
    task_service.delete(conn, task.id, "2026-10-13T10:02:00Z")
    disconnected = calendar_service.get_items_for_date(conn, item.local_date)[0]
    assert disconnected.task_id is None
    assert disconnected.notes == "Review mechanics"

    assert JournalService(conn).undo("2026-10-13T10:03:00Z") == "Delete task"
    reconnected = calendar_service.get_items_for_date(conn, item.local_date)[0]
    assert reconnected.task_id == task.id
