"""Integration tests for services/session_service.py."""

from __future__ import annotations

import pathlib

import pytest

from study_tracker.core.clock import FakeClock
from study_tracker.core.errors import ConflictError, ValidationError
from study_tracker.db import tasks_repo
from study_tracker.db.connection import get_connection
from study_tracker.db.migrate import run_migrations
from study_tracker.services import session_service, task_service


@pytest.fixture()
def conn(tmp_path: pathlib.Path):
    db_path = tmp_path / "test.db"
    c = get_connection(db_path)
    run_migrations(c, db_path)
    yield c
    c.close()


CLOCK = FakeClock("2026-10-13T12:00:00Z")


class TestManualTimed:
    def test_add_timed_session_success(self, conn):
        sess = session_service.add_manual_timed(
            conn,
            subject_id=1,
            start_utc="2026-10-13T08:00:00Z",
            end_utc="2026-10-13T09:30:00Z",
            duration_secs=5400,
            created_at=CLOCK.now_utc(),
        )
        assert sess.id > 0
        assert sess.start_utc == "2026-10-13T08:00:00Z"
        assert sess.end_utc == "2026-10-13T09:30:00Z"
        assert sess.duration_secs == 5400
        assert sess.local_date == "2026-10-13"

    def test_touching_sessions_allowed(self, conn):
        # Session 1: 08:00 to 09:00
        session_service.add_manual_timed(
            conn,
            subject_id=1,
            start_utc="2026-10-13T08:00:00Z",
            end_utc="2026-10-13T09:00:00Z",
            created_at=CLOCK.now_utc(),
        )
        # Session 2: 09:00 to 10:00 (exact boundary touch)
        s2 = session_service.add_manual_timed(
            conn,
            subject_id=1,
            start_utc="2026-10-13T09:00:00Z",
            end_utc="2026-10-13T10:00:00Z",
            created_at=CLOCK.now_utc(),
        )
        assert s2.id > 0

    def test_overlap_rejected(self, conn):
        session_service.add_manual_timed(
            conn,
            subject_id=1,
            start_utc="2026-10-13T08:00:00Z",
            end_utc="2026-10-13T09:00:00Z",
            created_at=CLOCK.now_utc(),
        )
        # Overlap by 1 second: 08:59:59 to 10:00
        with pytest.raises(ConflictError, match="overlaps"):
            session_service.add_manual_timed(
                conn,
                subject_id=1,
                start_utc="2026-10-13T08:59:59Z",
                end_utc="2026-10-13T10:00:00Z",
                created_at=CLOCK.now_utc(),
            )

    def test_edit_ignores_itself_in_overlap(self, conn):
        s = session_service.add_manual_timed(
            conn,
            subject_id=1,
            start_utc="2026-10-13T08:00:00Z",
            end_utc="2026-10-13T09:00:00Z",
            created_at=CLOCK.now_utc(),
        )
        # Update same session to 08:00 - 08:30 (overlaps original span, but itself!)
        updated = session_service.update(
            conn,
            s.id,
            subject_id=1,
            task_id=None,
            local_date=s.local_date,
            start_utc="2026-10-13T08:00:00Z",
            end_utc="2026-10-13T08:30:00Z",
            duration_secs=1800,
            session_type="manual_timed",
            notes="updated",
            utc_offset_mins=0,
            now_utc=CLOCK.now_utc(),
        )
        assert updated.duration_secs == 1800

    def test_end_before_start_rejected(self, conn):
        with pytest.raises(ValidationError, match="after start"):
            session_service.add_manual_timed(
                conn,
                subject_id=1,
                start_utc="2026-10-13T09:00:00Z",
                end_utc="2026-10-13T08:00:00Z",
                created_at=CLOCK.now_utc(),
            )

    def test_start_in_future_rejected(self, conn):
        with pytest.raises(ValidationError, match="future"):
            session_service.add_manual_timed(
                conn,
                subject_id=1,
                start_utc="2026-10-13T13:00:00Z",  # Clock is at 12:00:00Z
                end_utc="2026-10-13T14:00:00Z",
                created_at=CLOCK.now_utc(),
            )

    def test_duration_exceeding_span_rejected(self, conn):
        with pytest.raises(ValidationError, match="exceed"):
            session_service.add_manual_timed(
                conn,
                subject_id=1,
                start_utc="2026-10-13T08:00:00Z",
                end_utc="2026-10-13T09:00:00Z",
                duration_secs=4000,  # span is 3600
                created_at=CLOCK.now_utc(),
            )


class TestManualDuration:
    def test_add_duration_only(self, conn):
        sess = session_service.add_manual_duration(
            conn,
            subject_id=1,
            local_date="2026-10-13",
            duration_secs=7200,
            created_at=CLOCK.now_utc(),
        )
        assert sess.start_utc is None
        assert sess.end_utc is None
        assert sess.local_date == "2026-10-13"
        assert sess.duration_secs == 7200
        assert sess.session_type == "manual_duration"

    def test_zero_duration_rejected(self, conn):
        with pytest.raises(ValidationError):
            session_service.add_manual_duration(
                conn,
                subject_id=1,
                local_date="2026-10-13",
                duration_secs=0,
                created_at=CLOCK.now_utc(),
            )

    def test_exceeding_24h_daily_total_rejected(self, conn):
        with pytest.raises(ValidationError, match="24 hours"):
            session_service.add_manual_duration(
                conn,
                subject_id=1,
                local_date="2026-10-13",
                duration_secs=90000,
                created_at=CLOCK.now_utc(),
            )


class TestTaskIntegration:
    def test_session_moves_todo_task_to_inprogress_and_updates_time(self, conn):
        task = task_service.quick_add(
            conn, subject_id=1, title="Test Task", created_at=CLOCK.now_utc()
        )
        assert task.status == "todo"
        assert task.time_spent_secs == 0

        # Record a 1-hour session
        session_service.add_manual_duration(
            conn,
            subject_id=1,
            task_id=task.id,
            local_date="2026-10-13",
            duration_secs=3600,
            created_at=CLOCK.now_utc(),
        )

        refreshed_task = tasks_repo.get_by_id(conn, task.id)
        assert refreshed_task.status == "in_progress"
        assert refreshed_task.time_spent_secs == 3600
